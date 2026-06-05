"""Proves the setjmp/longjmp + handler-stack mechanism works under MCJIT on this
platform. This is the foundation the language feature is built on; CI re-runs it
on Windows, macOS, and Linux."""

import ctypes

import llvmlite.binding as llvm

from tawla import eh_runtime


def test_setjmp_longjmp_roundtrip_via_runtime():
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    eh_runtime.install()

    ir = r"""
declare i32 @tw_setjmp(i8*, i8*)
declare void @tw_longjmp(i8*, i32)
declare i8* @eh_top()
declare void @eh_push(i8*)

define void @thrower() {
  %t = call i8* @eh_top()
  call void @tw_longjmp(i8* %t, i32 42)
  ret void
}
define void @mid() { call void @thrower() ret void }

define i32 @run(i32 %do_throw) {
entry:
  %buf = alloca [256 x i8], align 16
  %p = getelementptr [256 x i8], [256 x i8]* %buf, i32 0, i32 0
  call void @eh_push(i8* %p)
  %r = call i32 @tw_setjmp(i8* %p, i8* null) #0
  %z = icmp eq i32 %r, 0
  br i1 %z, label %try, label %caught
try:
  %dt = icmp ne i32 %do_throw, 0
  br i1 %dt, label %boom, label %ok
boom:
  call void @mid()
  br label %ok
ok:
  ret i32 100
caught:
  ret i32 %r
}
attributes #0 = { returns_twice }
"""
    mod = llvm.parse_assembly(ir)
    mod.verify()
    tm = llvm.Target.from_default_triple().create_target_machine()
    ee = llvm.create_mcjit_compiler(mod, tm)
    ee.finalize_object()
    run = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32)(ee.get_function_address("run"))

    assert run(0) == 100   # normal path
    assert run(1) == 42    # throw two frames deep, caught
    assert run(0) == 100   # no corruption after a throw
