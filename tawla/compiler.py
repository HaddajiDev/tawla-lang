"""Runs the whole Tawla pipeline and runs the result through llvmlite's JIT.

The path: source text -> tokens -> AST -> typed AST -> LLVM IR -> JIT -> it runs.
"""

import ctypes

import llvmlite.binding as llvm

from . import gc_runtime
from .codegen import build_module
from .lexer import tokenize
from .monomorphize import monomorphize
from .parser import parse
from .sema import check as type_check

_initialized = False


def _initialize() -> None:
    """Wake up LLVM's native backend. Fine to call as often as you want — it only
    does the work once.

    Heads up: llvmlite >= 0.45 dropped the old top-level ``llvm.initialize()``, but
    these per-component ones are still required before we generate any code.
    """
    global _initialized
    if _initialized:
        return
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    _initialized = True


def run_source(src: str) -> int:
    """Compile some Tawla, run its `main`, and hand back the exit code.

    Programs talk to the outside world through `print`, so the return value is
    almost always 0 — it's really just the process exit status.
    """
    tokens = tokenize(src)
    ast = parse(tokens)
    ast = monomorphize(ast)
    type_check(ast)
    module = build_module(ast)

    _initialize()
    gc_runtime.install()
    target_machine = llvm.Target.from_default_triple().create_target_machine()
    module.triple = llvm.get_process_triple()
    module.data_layout = str(target_machine.target_data)

    mod_ref = llvm.parse_assembly(str(module))
    mod_ref.verify()

    engine = llvm.create_mcjit_compiler(mod_ref, target_machine)
    engine.finalize_object()

    func_ptr = engine.get_function_address("main")
    main_fn = ctypes.CFUNCTYPE(ctypes.c_int32)(func_ptr)
    return main_fn()
