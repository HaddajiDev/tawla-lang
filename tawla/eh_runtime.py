"""Exception-handling runtime: a handler stack + setjmp/longjmp, handed to the
JIT via llvm.add_symbol (same pattern as gc_runtime).

`fuck_around` installs a jmp_buf on the stack; a throw/panic looks up the top
handler and longjmps to it. setjmp/longjmp must save/restore the machine context.

On Unix we use libc's setjmp/longjmp (pure register restore, no SEH). On Windows
the CRT's longjmp does SEH-based stack unwinding (RtlUnwindEx), which is unsafe
through JIT-compiled frames that have no registered unwind info — it crashes,
especially inside a PyInstaller-frozen binary. So on Windows we provide our own
setjmp/longjmp as tiny naked functions (pure register save/restore, no unwind),
assembled by LLVM at startup into a small private module.
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


# --- Windows: our own setjmp/longjmp (naked, pure register save/restore) -------
#
# Win64 ABI: arg1 = RCX (jmp_buf), arg2 = EDX (longjmp value), return in RAX.
# Callee-saved registers we must preserve: RBX, RBP, RDI, RSI, R12-R15, RSP, plus
# XMM6-XMM15. jmp_buf layout (offsets into the 256-byte buffer codegen allocates):
#   0..56  rbx,rbp,rdi,rsi,r12,r13,r14,r15
#   64     caller rsp     72     return address
#   80..224 xmm6..xmm15 (16 bytes each)
_WIN_SETJMP = [
    "movq %rbx, 0(%rcx)", "movq %rbp, 8(%rcx)", "movq %rdi, 16(%rcx)",
    "movq %rsi, 24(%rcx)", "movq %r12, 32(%rcx)", "movq %r13, 40(%rcx)",
    "movq %r14, 48(%rcx)", "movq %r15, 56(%rcx)",
    "leaq 8(%rsp), %rax", "movq %rax, 64(%rcx)",
    "movq (%rsp), %rax", "movq %rax, 72(%rcx)",
    "movups %xmm6, 80(%rcx)", "movups %xmm7, 96(%rcx)", "movups %xmm8, 112(%rcx)",
    "movups %xmm9, 128(%rcx)", "movups %xmm10, 144(%rcx)", "movups %xmm11, 160(%rcx)",
    "movups %xmm12, 176(%rcx)", "movups %xmm13, 192(%rcx)", "movups %xmm14, 208(%rcx)",
    "movups %xmm15, 224(%rcx)",
    "xorl %eax, %eax", "ret",
]
_WIN_LONGJMP = [
    "movq 0(%rcx), %rbx", "movq 8(%rcx), %rbp", "movq 16(%rcx), %rdi",
    "movq 24(%rcx), %rsi", "movq 32(%rcx), %r12", "movq 40(%rcx), %r13",
    "movq 48(%rcx), %r14", "movq 56(%rcx), %r15",
    "movups 80(%rcx), %xmm6", "movups 96(%rcx), %xmm7", "movups 112(%rcx), %xmm8",
    "movups 128(%rcx), %xmm9", "movups 144(%rcx), %xmm10", "movups 160(%rcx), %xmm11",
    "movups 176(%rcx), %xmm12", "movups 192(%rcx), %xmm13", "movups 208(%rcx), %xmm14",
    "movups 224(%rcx), %xmm15",
    "movq 72(%rcx), %r8", "movq 64(%rcx), %rsp",
    "movl %edx, %eax", "testl %eax, %eax", "jnz 1f", "movl $$1, %eax", "1:",
    "jmpq *%r8",
]

_asm_engine = None  # keep the JIT'd setjmp/longjmp mapped for the process lifetime


def _build_windows_sjlj() -> None:
    """Assemble our naked setjmp/longjmp and bind tw_setjmp / tw_longjmp to them."""
    global _asm_engine
    if _asm_engine is not None:
        return
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    llvm.initialize_native_asmparser()  # required to assemble inline asm
    nl = r"\0A"
    ir = (
        'define i32 @tw_setjmp(i8* %buf, i8* %u) #0 {\n'
        '  call void asm sideeffect "' + nl.join(_WIN_SETJMP) + '", "~{memory}"()\n'
        '  unreachable\n}\n'
        'define void @tw_longjmp(i8* %buf, i32 %val) #0 {\n'
        '  call void asm sideeffect "' + nl.join(_WIN_LONGJMP) + '", "~{memory}"()\n'
        '  unreachable\n}\n'
        'attributes #0 = { naked nounwind }\n'
    )
    mod = llvm.parse_assembly(ir)
    mod.verify()
    tm = llvm.Target.from_default_triple().create_target_machine()
    eng = llvm.create_mcjit_compiler(mod, tm)
    eng.finalize_object()
    llvm.add_symbol("tw_setjmp", eng.get_function_address("tw_setjmp"))
    llvm.add_symbol("tw_longjmp", eng.get_function_address("tw_longjmp"))
    _asm_engine = eng


def _bind_unix_sjlj() -> None:
    """Bind tw_setjmp / tw_longjmp to libc setjmp/longjmp (no SEH on Unix)."""
    crt = ctypes.CDLL(None)
    llvm.add_symbol("tw_setjmp", ctypes.cast(crt.setjmp, ctypes.c_void_p).value)
    llvm.add_symbol("tw_longjmp", ctypes.cast(crt.longjmp, ctypes.c_void_p).value)


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
        if sys.platform == "win32":
            _build_windows_sjlj()
        else:
            _bind_unix_sjlj()
        _registered = True
    STATE.reset()
