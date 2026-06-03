"""Number-to-string conversion for Tawla's toString builtin, hosted in Python.

`snprintf` isn't reliably resolvable as a JIT symbol on every C runtime
(Windows in particular), so formatting a number into a string is done here and
the result is copied onto the GC heap, the same way io_runtime returns strings.
"""

import ctypes

import llvmlite.binding as llvm

from .gc_runtime import HEAP


def _alloc(s: str) -> int:
    data = s.encode("utf-8") + b"\x00"
    addr = HEAP.alloc(len(data))
    ctypes.memmove(addr, data, len(data))
    return addr


_c_from_int = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int32)(lambda n: _alloc(str(n)))
_c_from_float = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_double)(lambda x: _alloc(format(x, "g")))

_CALLBACKS = [_c_from_int, _c_from_float]
_registered = False


def install() -> None:
    """Register num_to_str_i / num_to_str_f with llvmlite."""
    global _registered
    if _registered:
        return
    cast = ctypes.cast
    llvm.add_symbol("num_to_str_i", cast(_c_from_int, ctypes.c_void_p).value)
    llvm.add_symbol("num_to_str_f", cast(_c_from_float, ctypes.c_void_p).value)
    _registered = True
