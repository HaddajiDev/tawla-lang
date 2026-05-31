"""The native side of Tawla's IO library.

The friendly names (`readInt`, `readLine`, ...) live in `stdlib/IO.twl` as plain
Tawla functions; each one just forwards to one of the `__io_*` primitives here.
Reading is done in Python so stdin behaves the same on every OS, and any string
we hand back is allocated on the GC heap so the collector tracks it like any
other Tawla string.
"""

import ctypes

import llvmlite.binding as llvm

from .gc_runtime import HEAP


def _read_int() -> int:
    try:
        return int(input())
    except (EOFError, ValueError):
        return 0


def _read_float() -> float:
    try:
        return float(input())
    except (EOFError, ValueError):
        return 0.0


def _read_line() -> int:
    try:
        line = input()
    except EOFError:
        line = ""
    data = line.encode("utf-8") + b"\x00"
    addr = HEAP.alloc(len(data))
    ctypes.memmove(addr, data, len(data))
    return addr


_c_read_int = ctypes.CFUNCTYPE(ctypes.c_int32)(_read_int)
_c_read_float = ctypes.CFUNCTYPE(ctypes.c_double)(_read_float)
_c_read_line = ctypes.CFUNCTYPE(ctypes.c_void_p)(_read_line)

_CALLBACKS = [_c_read_int, _c_read_float, _c_read_line]
_registered = False


def install() -> None:
    """Register the IO primitives with llvmlite so the JIT can call them."""
    global _registered
    if _registered:
        return
    cast = ctypes.cast
    llvm.add_symbol("io_read_int", cast(_c_read_int, ctypes.c_void_p).value)
    llvm.add_symbol("io_read_float", cast(_c_read_float, ctypes.c_void_p).value)
    llvm.add_symbol("io_read_line", cast(_c_read_line, ctypes.c_void_p).value)
    _registered = True
