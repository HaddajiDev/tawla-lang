"""Exception-handling runtime: a handler stack + the C setjmp/longjmp, handed to
the JIT via llvm.add_symbol (same pattern as gc_runtime).

`fuck_around` installs a jmp_buf on the stack; a throw/panic looks up the top
handler and longjmps to it. setjmp/longjmp must be the real C functions (they
save/restore the machine context); the stack and message live here in Python.
"""

import ctypes
import sys

import llvmlite.binding as llvm


class EHState:
    def __init__(self) -> None:
        self.handlers: list[int] = []
        self.msg: int = 0

    def push(self, buf: int) -> None:
        self.handlers.append(buf or 0)

    def pop(self) -> None:
        if self.handlers:
            self.handlers.pop()

    def top(self) -> int:
        return self.handlers[-1] if self.handlers else 0

    def set_msg(self, p: int) -> None:
        self.msg = p or 0

    def get_msg(self) -> int:
        return self.msg

    def reset(self) -> None:
        self.handlers.clear()
        self.msg = 0


STATE = EHState()

_push = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(lambda b: STATE.push(b))
_pop = ctypes.CFUNCTYPE(None)(lambda: STATE.pop())
_top = ctypes.CFUNCTYPE(ctypes.c_void_p)(lambda: STATE.top())
_set_msg = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(lambda p: STATE.set_msg(p))
_get_msg = ctypes.CFUNCTYPE(ctypes.c_void_p)(lambda: STATE.get_msg())

_CALLBACKS = [_push, _pop, _top, _set_msg, _get_msg]

# Real C setjmp/longjmp. Windows: msvcrt._setjmp is the non-SEH form and works
# under the JIT when called as (buf, NULL); plain `setjmp` is SEH-based and
# crashes. Unix: libc setjmp is 1-arg; the extra NULL the IR passes is ignored.
if sys.platform == "win32":
    _crt = ctypes.CDLL("msvcrt.dll")
    _setjmp_addr = ctypes.cast(_crt._setjmp, ctypes.c_void_p).value
    _longjmp_addr = ctypes.cast(_crt.longjmp, ctypes.c_void_p).value
else:
    _crt = ctypes.CDLL(None)
    _setjmp_addr = ctypes.cast(_crt.setjmp, ctypes.c_void_p).value
    _longjmp_addr = ctypes.cast(_crt.longjmp, ctypes.c_void_p).value

_registered = False


def install() -> None:
    """Register our symbols with llvmlite, then clear state for a fresh run."""
    global _registered
    if not _registered:
        cast = ctypes.cast
        llvm.add_symbol("eh_push", cast(_push, ctypes.c_void_p).value)
        llvm.add_symbol("eh_pop", cast(_pop, ctypes.c_void_p).value)
        llvm.add_symbol("eh_top", cast(_top, ctypes.c_void_p).value)
        llvm.add_symbol("eh_set_msg", cast(_set_msg, ctypes.c_void_p).value)
        llvm.add_symbol("eh_msg", cast(_get_msg, ctypes.c_void_p).value)
        llvm.add_symbol("tw_setjmp", _setjmp_addr)
        llvm.add_symbol("tw_longjmp", _longjmp_addr)
        _registered = True
    STATE.reset()
