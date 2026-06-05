# Exception Handling (`fuck_around` / `find_out`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add try/catch to Tawla — `fuck_around { } find_out (e) { }` plus `throw "msg";` — catching explicit throws and the built-in errors (panic, null-deref, array-bounds, string-index).

**Architecture:** Parse-time new AST nodes (`TryCatch`, `Throw`). The catch mechanism is C `setjmp`/`longjmp` driven by a Python-hosted handler-stack runtime (`eh_runtime.py`), already proven in a spike. Codegen installs a `jmp_buf` handler per `fuck_around`, reroutes every error site through a `_raise` helper that either `longjmp`s to the nearest handler or (if none) prints and `exit(1)`s as today. The caught value is always the error message `string`.

**Tech Stack:** Python 3.11+, llvmlite (LLVM IR + MCJIT), ctypes, pytest.

**Reference spec:** `docs/superpowers/specs/2026-06-05-exception-handling-design.md` (mechanism verified — see its "Verified mechanism" section).

---

## Verified facts (from the codebase + spike)

- `setjmp`/`longjmp` round-trip works under MCJIT using, on Windows,
  `msvcrt._setjmp(buf, NULL)` (declared `i32 @tw_setjmp(i8*, i8*)`, called with a
  NULL 2nd arg, marked `returns_twice`); on Unix, libc `setjmp` (the extra NULL
  arg is ignored by the ABI). `longjmp` is `void @tw_longjmp(i8*, i32)`.
- `codegen.py` error sites all do `printf(msg); exit(1); unreachable()`:
  - `panic` at ~line 916: `printf(_fmt_str, msg)` then `exit`.
  - `_str_oob` (~717), `_null_check` (~729), `_bounds_check` (~744): `printf(_str_ptr(<msg global>))` then `exit`.
- `_fmt_str` = `"%s\n"`, `_fmt_str_raw` = `"%s"`.
- GC roots: `_begin_function` stores `gc_root_depth()` into `self._depth_slot`;
  `_emit_root_restore()` calls `gc_root_settop(load _depth_slot)`. `Return`
  codegen (~613) calls `_emit_root_restore()` then `ret`.
- Statement dispatch is `_gen_stmt` (~545); blocks via `_gen_block` (~532).
- `_alloca(name, typ)` allocates in the entry block via `self.alloca_builder`.
- Runtime registration pattern: see `gc_runtime.install()`; runtimes are
  installed in `compiler.py` `run_file` (~lines 61-65).
- Statement parser dispatch: `parser.py` `statement()` (~line 371).
- String type: `self._llvm_type("string")` (an `i8*`).

## File Structure

| File | Change |
|------|--------|
| `tawla/eh_runtime.py` | **New.** Handler-stack runtime + setjmp/longjmp bindings. |
| `tawla/compiler.py` | Register `eh_runtime.install()`. |
| `tawla/tokens.py` | `KW_FUCK_AROUND`, `KW_FIND_OUT`, `KW_THROW` + keyword map. |
| `tawla/ast_nodes.py` | `TryCatch`, `Throw` nodes. |
| `tawla/parser.py` | Parse the blocks + `throw`; dispatch in `statement()`. |
| `tawla/sema.py` | Type-check `throw`/catch var; reject break/continue across a try. |
| `tawla/monomorphize.py` | Recurse through the new nodes. |
| `tawla/codegen.py` | eh decls, `_raise`, `Throw`, `TryCatch`, reroute traps, return-unwind. |
| `tawlac.spec` | Add `tawla.eh_runtime` to `hiddenimports`. |
| `tests/test_eh_runtime.py`, `tests/test_m36.py` | New tests. |
| `examples/errors.twl`, README, docs, `pyproject.toml`+`__init__.py` | Example, docs, version 1.5.0. |

---

## Task 1: `eh_runtime.py` + JIT round-trip test + compiler wiring

**Files:**
- Create: `tawla/eh_runtime.py`
- Modify: `tawla/compiler.py` (import + install)
- Create: `tests/test_eh_runtime.py`

- [ ] **Step 1: Create the runtime**

Create `tawla/eh_runtime.py`:

```python
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
```

- [ ] **Step 2: Wire it into the compiler**

In `tawla/compiler.py`, add `eh_runtime` to the runtime import (line ~11):

```python
from . import eh_runtime, fetch_runtime, gc_runtime, http_runtime, io_runtime, str_runtime
```

and call its install alongside the others in `run_file` (after `gc_runtime.install()`):

```python
    gc_runtime.install()
    eh_runtime.install()
    io_runtime.install()
    http_runtime.install()
    str_runtime.install()
    fetch_runtime.install()
```

- [ ] **Step 3: Write the JIT round-trip test (permanent spike)**

Create `tests/test_eh_runtime.py`:

```python
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
```

- [ ] **Step 4: Run the test**

Run: `venv/Scripts/python.exe -m pytest tests/test_eh_runtime.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tawla/eh_runtime.py tawla/compiler.py tests/test_eh_runtime.py
git commit -m "Add eh_runtime (handler stack + setjmp/longjmp) and JIT round-trip test"
```

---

## Task 2: Tokens, lexer, AST, parser

**Files:**
- Modify: `tawla/tokens.py`, `tawla/ast_nodes.py`, `tawla/parser.py`
- Test: `tests/test_m36.py` (new)

- [ ] **Step 1: Write the failing parse test**

Create `tests/test_m36.py`:

```python
"""M36: exception handling (fuck_around / find_out / throw)."""

from tawla.lexer import tokenize
from tawla.parser import parse
from tawla.ast_nodes import TryCatch, Throw


def _stmts(body):
    # parse a function body's statements out of a tiny program
    items = parse(tokenize("class Main { void main() { " + body + " } }"))
    main_cls = items[0]
    method = main_cls.methods[0]
    return method.body


def test_parses_trycatch_with_var():
    body = 'fuck_around { throw "x"; } find_out (e) { print(e); }'
    stmts = _stmts(body)
    tc = stmts[0]
    assert isinstance(tc, TryCatch)
    assert tc.catch_var == "e"
    assert isinstance(tc.try_body[0], Throw)


def test_parses_bare_find_out():
    stmts = _stmts("fuck_around { panic(\"boom\"); } find_out { print(\"caught\"); }")
    assert isinstance(stmts[0], TryCatch)
    assert stmts[0].catch_var is None
```

(If `ClassDecl`/method attribute names differ, adjust `_stmts` to match how
`parse()` exposes a method body — check an existing parser test or `ast_nodes.py`.
The shape used here: `items[0].methods[0].body`.)

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_m36.py -v`
Expected: FAIL — `ImportError` for `TryCatch`/`Throw` (nodes don't exist).

- [ ] **Step 3: Add token kinds**

In `tawla/tokens.py`, add to the `TokenKind` enum (near the other `KW_*`):

```python
    KW_FUCK_AROUND = auto()
    KW_FIND_OUT = auto()
    KW_THROW = auto()
```

and to the `KEYWORDS` dict:

```python
    "fuck_around": TokenKind.KW_FUCK_AROUND,
    "find_out": TokenKind.KW_FIND_OUT,
    "throw": TokenKind.KW_THROW,
```

(`fuck_around` and `find_out` are ordinary identifiers to the lexer — underscores
are identifier characters — so no lexer logic changes.)

- [ ] **Step 4: Add AST nodes**

In `tawla/ast_nodes.py`, add (near the other statement nodes):

```python
@dataclass
class Throw(Stmt):
    value: Expr


@dataclass
class TryCatch(Stmt):
    try_body: list
    catch_var: str | None
    catch_body: list
```

- [ ] **Step 5: Parse the constructs**

In `tawla/parser.py`, import the new nodes (add `Throw, TryCatch` to the
`ast_nodes` import block). Add two parse methods to the parser class:

```python
    def throw_stmt(self) -> Stmt:
        self.expect(TokenKind.KW_THROW)
        value = self.expr()
        self.expect(TokenKind.SEMICOLON)
        return Throw(value)

    def try_catch_stmt(self) -> Stmt:
        self.expect(TokenKind.KW_FUCK_AROUND)
        try_body = self.block()
        self.expect(TokenKind.KW_FIND_OUT)
        catch_var = None
        if self.current.kind is TokenKind.LPAREN:
            self.advance()
            catch_var = self.expect(TokenKind.IDENT).text
            self.expect(TokenKind.RPAREN)
        catch_body = self.block()
        return TryCatch(try_body, catch_var, catch_body)
```

Then dispatch them in `statement()` (the `match self.current.kind` block, ~line
374) by adding cases:

```python
            case TokenKind.KW_THROW:
                return self.throw_stmt()
            case TokenKind.KW_FUCK_AROUND:
                return self.try_catch_stmt()
```

- [ ] **Step 6: Run the parse test**

Run: `venv/Scripts/python.exe -m pytest tests/test_m36.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tawla/tokens.py tawla/ast_nodes.py tawla/parser.py tests/test_m36.py
git commit -m "Parse fuck_around / find_out / throw"
```

---

## Task 3: Sema + monomorphize

**Files:**
- Modify: `tawla/sema.py`, `tawla/monomorphize.py`
- Test: `tests/test_m36.py`

(Note: Tawla has **no `break`/`continue` statements**, so there is no loop-escape
restriction to implement — only `throw` typing and the catch-var scope.)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_m36.py`:

```python
def test_sema_throw_requires_string(run_twl):
    r = run_twl('fuck_around { throw 5; } find_out (e) { print(e); }')
    assert r.returncode != 0
    assert "string" in r.stderr
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_m36.py -k sema -v`
Expected: FAIL — sema raises a different/no error for `throw 5;` (the message
won't contain "string" the way we want).

- [ ] **Step 3: Type-check the new nodes in sema**

In `tawla/sema.py`, import `Throw, TryCatch` from `ast_nodes`. `_check_stmt`
(~line 405) is an `if/elif isinstance(...)` chain that recurses into bodies with
`for s in body: self._check_stmt(s)`, and scopes block-locals by save/restore of
`self.scope` (see the `For` case at ~line 483). Add two `elif` branches to that
chain (e.g. after the `Return` branch):

```python
        elif isinstance(stmt, Throw):
            t = self._check_expr(stmt.value)
            if t != STRING:
                raise SemaError(f"throw requires a string, got {t}")

        elif isinstance(stmt, TryCatch):
            for s in stmt.try_body:
                self._check_stmt(s)
            saved = dict(self.scope)          # catch var is scoped to the catch body
            if stmt.catch_var is not None:
                self.scope[stmt.catch_var] = STRING
            for s in stmt.catch_body:
                self._check_stmt(s)
            self.scope = saved
```

(`STRING` is the module-level `Type("string")` at sema.py line 63; `_check_expr`
and `_check_stmt` already exist.)

- [ ] **Step 4: Pass the new nodes through monomorphize**

In `tawla/monomorphize.py`, find where statements are walked (the function that
recurses into statement bodies) and add cases so `TryCatch` recurses into
`try_body` and `catch_body`, and `Throw` recurses into its `value`. Match the
existing pattern (most statements are walked structurally). Example, mirroring the
file's style:

```python
        if isinstance(stmt, TryCatch):
            self._walk_block(stmt.try_body)
            self._walk_block(stmt.catch_body)
            return
        if isinstance(stmt, Throw):
            self._walk_expr(stmt.value)
            return
```

(If monomorphize is a no-op pass-through for plain statements, ensure these nodes
don't raise "unknown statement" — add them to whatever dispatch exists.)

- [ ] **Step 5: Run the sema test**

Run: `venv/Scripts/python.exe -m pytest tests/test_m36.py -k sema -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite (no regressions in sema/monomorphize)**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all prior tests still pass; the codegen tests for fuck_around are not
written yet.

- [ ] **Step 7: Commit**

```bash
git add tawla/sema.py tawla/monomorphize.py tests/test_m36.py
git commit -m "Type-check throw/find_out; restrict break/continue across a try"
```

---

## Task 4: Codegen — throw, try/catch, and reroute panic

**Files:**
- Modify: `tawla/codegen.py`
- Test: `tests/test_m36.py`

- [ ] **Step 1: Write the failing end-to-end tests**

Append to `tests/test_m36.py`:

```python
def test_throw_caught(run_twl):
    src = 'fuck_around { throw "boom"; print("unreached"); } find_out (e) { print(e); }'
    assert run_twl(src).stdout == "boom\n"


def test_bare_find_out(run_twl):
    src = 'fuck_around { throw "x"; } find_out { print("caught"); }'
    assert run_twl(src).stdout == "caught\n"


def test_panic_caught(run_twl):
    src = 'fuck_around { panic("nope"); } find_out (e) { print(e); } print("after");'
    assert run_twl(src).stdout == "nope\nafter\n"


def test_uncaught_throw_exits_nonzero(run_twl):
    r = run_twl('throw "unhandled";')
    assert r.returncode != 0
    assert "unhandled" in r.stdout


def test_no_throw_runs_try_only(run_twl):
    src = 'fuck_around { print("ok"); } find_out (e) { print("nope"); }'
    assert run_twl(src).stdout == "ok\n"


def test_nested_inner_catches(run_twl):
    src = (
        'fuck_around {'
        '  fuck_around { throw "inner"; } find_out (e) { print(e); }'
        '  print("outer continues");'
        '} find_out (e) { print("outer caught"); }'
    )
    assert run_twl(src).stdout == "inner\nouter continues\n"


def test_rethrow_to_outer(run_twl):
    src = (
        'fuck_around {'
        '  fuck_around { throw "x"; } find_out (e) { throw "y"; }'
        '} find_out (e) { print(e); }'
    )
    assert run_twl(src).stdout == "y\n"


def test_return_from_try(run_twl):
    src = (
        "class Main {"
        "  int f() { fuck_around { return 7; } find_out (e) { return -1; } }"
        "  void main() { print(this.f()); }"
        "}"
    )
    assert run_twl(src).stdout == "7\n"


def test_return_from_catch(run_twl):
    src = (
        "class Main {"
        '  int f() { fuck_around { throw "x"; return 7; } find_out (e) { return -1; } }'
        "  void main() { print(this.f()); }"
        "}"
    )
    assert run_twl(src).stdout == "-1\n"
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_m36.py -k "throw or find_out or panic or nested or rethrow or return or try" -v`
Expected: FAIL — codegen raises `cannot codegen statement Throw/TryCatch`.

- [ ] **Step 3: Declare the EH functions**

In `tawla/codegen.py`, in the method that declares external functions (where
`self.printf`, `self.exit`, `self.gc_root_*` are created, ~lines 93-128), add:

```python
        self.eh_push = ir.Function(self.module, ir.FunctionType(void, [i8ptr]), name="eh_push")
        self.eh_pop = ir.Function(self.module, ir.FunctionType(void, []), name="eh_pop")
        self.eh_top = ir.Function(self.module, ir.FunctionType(i8ptr, []), name="eh_top")
        self.eh_set_msg = ir.Function(self.module, ir.FunctionType(void, [i8ptr]), name="eh_set_msg")
        self.eh_msg = ir.Function(self.module, ir.FunctionType(i8ptr, []), name="eh_msg")
        self.tw_setjmp = ir.Function(self.module, ir.FunctionType(i32, [i8ptr, i8ptr]), name="tw_setjmp")
        self.tw_setjmp.attributes.add("returns_twice")
        self.tw_longjmp = ir.Function(self.module, ir.FunctionType(void, [i8ptr, i32]), name="tw_longjmp")
        self.tw_longjmp.attributes.add("noreturn")
```

(Use whatever names this file uses for the `void`/`i32`/`i8ptr` IR types — they
are module-level constants in `codegen.py`.)

- [ ] **Step 4: Initialize the handler counter**

In `_begin_function` (~line 450), after setting up `self._depth_slot`, add:

```python
        self._active_handlers = 0
```

(This tracks how many EH handlers are live at the current codegen point, for
`return` unwinding.)

- [ ] **Step 5: Add the `_raise` helper**

Add this method to the codegen class (near `_null_check`):

```python
    def _raise(self, msg_ptr: ir.Value) -> None:
        """Raise an error carrying `msg_ptr` (an i8* message). If a handler is
        installed, longjmp to it; otherwise print and exit(1) (today's behavior).
        Terminates the current block."""
        func = self.builder.function
        top = self.builder.call(self.eh_top, [])
        has = self.builder.icmp_signed("!=", top, ir.Constant(i8ptr, None))
        caught_bb = func.append_basic_block("raise.caught")
        uncaught_bb = func.append_basic_block("raise.uncaught")
        self.builder.cbranch(has, caught_bb, uncaught_bb)

        self.builder.position_at_end(caught_bb)
        self.builder.call(self.eh_set_msg, [msg_ptr])
        self.builder.call(self.tw_longjmp, [top, ir.Constant(i32, 1)])
        self.builder.unreachable()

        self.builder.position_at_end(uncaught_bb)
        self.builder.call(self.printf, [self._str_ptr(self._fmt_str), msg_ptr])
        self.builder.call(self.exit, [ir.Constant(i32, 1)])
        self.builder.unreachable()
```

- [ ] **Step 6: Reroute `panic` through `_raise`**

In `_gen_stmt`/the builtin call site, replace the `panic` body (~line 916):

```python
        if name == "panic":
            msg = self._gen_expr(args[0])
            self.builder.call(self.printf, [self._str_ptr(self._fmt_str), msg])
            return self.builder.call(self.exit, [ir.Constant(i32, 1)])
```

with:

```python
        if name == "panic":
            msg = self._gen_expr(args[0])
            self._raise(msg)
            return None
```

- [ ] **Step 7: Codegen `Throw`**

In `_gen_stmt`, add (before the final `raise CodeGenError`):

```python
        if isinstance(stmt, Throw):
            msg = self._gen_expr(stmt.value)
            self._raise(msg)
            return
```

- [ ] **Step 8: Codegen `TryCatch`**

Add a `_gen_trycatch` method and dispatch it from `_gen_stmt`:

```python
        if isinstance(stmt, TryCatch):
            self._gen_trycatch(stmt)
            return
```

```python
    def _gen_trycatch(self, stmt: TryCatch) -> None:
        func = self.builder.function
        # jmp_buf + saved GC depth, both in the entry block
        buf = self.alloca_builder.alloca(ir.ArrayType(i8, 256), name="jmpbuf")
        buf_ptr = self.builder.bitcast(buf, i8ptr)
        depth_slot = self.alloca_builder.alloca(i32, name="try_depth")
        self.builder.store(self.builder.call(self.gc_root_depth, []), depth_slot)

        self.builder.call(self.eh_push, [buf_ptr])
        self._active_handlers += 1

        r = self.builder.call(self.tw_setjmp, [buf_ptr, ir.Constant(i8ptr, None)])
        is_zero = self.builder.icmp_signed("==", r, ir.Constant(i32, 0))
        try_bb = func.append_basic_block("try.body")
        catch_bb = func.append_basic_block("try.catch")
        after_bb = func.append_basic_block("try.after")
        self.builder.cbranch(is_zero, try_bb, catch_bb)

        # --- try body ---
        self.builder.position_at_end(try_bb)
        self._gen_block(stmt.try_body)
        if not self.builder.block.is_terminated:
            self.builder.call(self.eh_pop, [])
            self.builder.branch(after_bb)

        # handler is no longer active for the catch body / after
        self._active_handlers -= 1

        # --- catch body (reached via longjmp; handler still on the stack) ---
        self.builder.position_at_end(catch_bb)
        self.builder.call(self.eh_pop, [])
        self.builder.call(self.gc_root_settop, [self.builder.load(depth_slot)])
        if stmt.catch_var is not None:
            str_ty = self._llvm_type("string")
            slot = self._alloca(stmt.catch_var, str_ty)
            msg = self.builder.bitcast(self.builder.call(self.eh_msg, []), str_ty)
            self.builder.store(msg, slot)
            self.symbols[stmt.catch_var] = slot
            self._maybe_root(slot)
        self._gen_block(stmt.catch_body)
        if not self.builder.block.is_terminated:
            self.builder.branch(after_bb)

        self.builder.position_at_end(after_bb)
```

- [ ] **Step 9: Unwind handlers on `return`**

In `_gen_stmt`'s `Return` handling (~line 613), pop any active handlers *before*
the existing root-restore + `ret`. Change both branches so they first emit:

```python
        if isinstance(stmt, Return):
            for _ in range(self._active_handlers):
                self.builder.call(self.eh_pop, [])
            if stmt.value is None:
                self._emit_root_restore()
                self.builder.ret_void()
            else:
                ret_ty = self.builder.function.function_type.return_type
                val = self._coerce(self._gen_expr(stmt.value), ret_ty)
                self._emit_root_restore()
                self.builder.ret(val)
            return
```

(`_active_handlers` reflects how many handlers enclose this `return` lexically:
inside a try body it includes that try's handler; inside a catch body it does
not, because Step 8 decrements before generating the catch.)

- [ ] **Step 10: Run the codegen tests**

Run: `venv/Scripts/python.exe -m pytest tests/test_m36.py -v`
Expected: PASS (all M36 tests, including the parse/sema ones).

- [ ] **Step 11: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all pass (panic reroute must not break existing panic tests — uncaught
panic still prints the message and exits non-zero).

- [ ] **Step 12: Commit**

```bash
git add tawla/codegen.py tests/test_m36.py
git commit -m "Codegen throw + fuck_around/find_out; reroute panic via _raise"
```

---

## Task 5: Make built-in traps catchable (null, bounds, string-index)

**Files:**
- Modify: `tawla/codegen.py`
- Test: `tests/test_m36.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_m36.py`:

```python
def test_null_deref_caught(run_twl):
    src = (
        "class Box { public int n; public Box() { this.n = 1; } }"
        "class Main { void main() {"
        '  fuck_around { Box b; print(b.n); } find_out (e) { print("caught null"); }'
        "} }"
    )
    assert run_twl(src).stdout == "caught null\n"


def test_bounds_caught(run_twl):
    src = (
        'fuck_around { int[] a = new int[2]; print(a[5]); }'
        ' find_out (e) { print("caught oob"); }'
    )
    assert run_twl(src).stdout == "caught oob\n"
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_m36.py -k "null_deref or bounds" -v`
Expected: FAIL — the traps currently `exit(1)`, so the process dies inside the
`fuck_around` (no stdout, non-zero exit) instead of being caught.

- [ ] **Step 3: Add no-newline message globals**

In `tawla/codegen.py`, where `_oob_msg`, `_str_oob_msg`, `_null_msg` are defined
(lines ~101, 157, 161), add three companions without the trailing newline (the
`_fmt_str` in `_raise` adds the newline on the uncaught path):

```python
        self._oob_raw = self._global_string(b"array index out of bounds\0", "oob_raw")
        self._str_oob_raw = self._global_string(b"string index out of range\0", "str_oob_raw")
        self._null_raw = self._global_string(b"null reference\0", "null_raw")
```

- [ ] **Step 4: Reroute the three traps through `_raise`**

In `_str_oob` (~723-726), replace:

```python
        self.builder.call(self.printf, [self._str_ptr(self._str_oob_msg)])
        self.builder.call(self.exit, [ir.Constant(i32, 1)])
        self.builder.unreachable()
```

with:

```python
        self._raise(self._str_ptr(self._str_oob_raw))
```

In `_null_check` (~737-740), replace:

```python
        self.builder.call(self.printf, [self._str_ptr(self._null_msg)])
        self.builder.call(self.exit, [ir.Constant(i32, 1)])
        self.builder.unreachable()
```

with:

```python
        self._raise(self._str_ptr(self._null_raw))
```

In `_bounds_check` (~759-762), replace:

```python
        self.builder.call(self.printf, [self._str_ptr(self._oob_msg)])
        self.builder.call(self.exit, [ir.Constant(i32, 1)])
        self.builder.unreachable()
```

with:

```python
        self._raise(self._str_ptr(self._oob_raw))
```

(`_raise` itself terminates the block with `unreachable`/branches, so the
explicit `unreachable()` calls are removed.)

- [ ] **Step 5: Run the trap tests**

Run: `venv/Scripts/python.exe -m pytest tests/test_m36.py -k "null_deref or bounds" -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all pass. Existing uncaught-error tests (e.g. `test_m16` bounds) still
exit non-zero — now via `_raise`'s uncaught path, which prints
`array index out of bounds\n` (same visible text) and `exit(1)`.

- [ ] **Step 7: Commit**

```bash
git add tawla/codegen.py tests/test_m36.py
git commit -m "Make null/bounds/string-index errors catchable via _raise"
```

---

## Task 6: Example, docs, wiring, version bump, verification

**Files:**
- Create: `examples/errors.twl`
- Modify: `tawlac.spec`, `README.md`, `tawla_lang_docs/index.html`,
  `pyproject.toml`, `tawla/__init__.py`

- [ ] **Step 1: Create the example**

Create `examples/errors.twl`:

```tawla
// Exception handling: fuck_around (try) / find_out (catch) / throw.
// The caught value is always the error message (a string). Built-in errors
// like panic, null dereference, and array-out-of-bounds are catchable too.

class Main {
    void main() {
        fuck_around {
            throw "something broke";
        } find_out (e) {
            print(e);                 // something broke
        }

        fuck_around {
            int[] a = new int[2];
            print(a[9]);              // out of bounds
        } find_out (e) {
            print("recovered");       // recovered
        }

        // bare find_out ignores the message
        fuck_around {
            panic("boom");
        } find_out {
            print("handled");         // handled
        }
    }
}
```

- [ ] **Step 2: Verify the example runs**

Run: `venv/Scripts/python.exe -m tawla run examples/errors.twl`
Expected output:
```
something broke
recovered
handled
```

- [ ] **Step 3: Add eh_runtime to the PyInstaller spec**

In `tawlac.spec`, add `"tawla.eh_runtime"` to the `hiddenimports += [...]` list.

- [ ] **Step 4: Update the README**

In `README.md`, add a bullet in the "What the language can do" list (after the
`panic` bullet):

```markdown
- **Exceptions:** `fuck_around { ... } find_out (e) { ... }` is try/catch — `e`
  is the error message string. `throw "msg";` raises one, and built-in errors
  (`panic`, null dereference, array-out-of-bounds) are catchable too. Use bare
  `find_out { ... }` to ignore the message.
```

- [ ] **Step 5: Update the docs site**

In `tawla_lang_docs/index.html`, in the operators or a new "Errors" area of the
language guide, add a section describing `fuck_around`/`find_out`/`throw` with the
`examples/errors.twl` snippet (escape `<`/`>`/`&` as the other code blocks do).
Place a sidebar link if the section gets an `id`. (This is the separate docs
repo — committed/pushed in Step 9.)

- [ ] **Step 6: Bump the version to 1.5.0**

In `pyproject.toml` line 3: `version = "1.5.0"`.
In `tawla/__init__.py` line 3: `__version__ = "1.5.0"`.

- [ ] **Step 7: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 8: Rebuild the binary and smoke-test exceptions**

Run:
```bash
venv/Scripts/pyinstaller.exe tawlac.spec --clean --noconfirm
./dist/tawlac.exe run examples/errors.twl
```
Expected: `something broke` / `recovered` / `handled`, proving the EH runtime
(setjmp/longjmp + handler stack) works inside the frozen binary too.

- [ ] **Step 9: Commit (compiler repo) and push docs**

```bash
git add examples/errors.twl tawlac.spec README.md pyproject.toml tawla/__init__.py
git commit -m "Add errors example, docs, eh_runtime hiddenimport; bump to 1.5.0"
```

```bash
cd D:\Projects\tawla_lang_docs
git add index.html
git commit -m "Document fuck_around / find_out exception handling"
git push
cd D:\Projects\Tawla_lang
```

- [ ] **Step 10: (Optional) add throw/catch to the release smoke set**

To have CI verify EH on macOS/Linux, append a throw/catch line to
`examples/smoke.twl` (e.g. `fuck_around { throw "x"; } find_out (e) { print(e); }`
printing a known value) and update the workflow's smoke assertion accordingly.
This confirms the Unix setjmp binding at release time.

---

## Done criteria

- `fuck_around { throw "m"; } find_out (e) { print(e); }` prints `m`; bare
  `find_out` works; `panic`, null-deref, and bounds errors are catchable.
- Uncaught `throw`/errors still print the message and exit non-zero (backward
  compatible).
- Nesting, rethrow, and `return` out of try/catch behave per the spec.
- `tests/test_eh_runtime.py` + `tests/test_m36.py` pass; full suite green.
- `dist/tawlac.exe run examples/errors.twl` works; version is `1.5.0`.
- Release binaries (on a `v1.5.0` tag) build and smoke-test on all three OSes.

## Release (on the user's go-ahead)

After merge to `main` and push: `git tag v1.5.0 && git push origin v1.5.0` to
build the binaries, then build + publish 1.5.0 to PyPI. Not automatic.
