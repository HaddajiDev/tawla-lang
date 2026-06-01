# null and Default-Initialized Variables — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `null` literal (assignable to reference types only) plus declarations without initializers that default to the type's zero value, with clean runtime "null reference" errors on misuse.

**Architecture:** Threads through the existing pipeline (tokens → lexer-free keyword → AST → parser → sema → monomorphize → codegen). `null` gets a dedicated codegen "sentinel" pointer type so it's never confused with a `string` (also `i8*`); `_coerce` turns the sentinel into a typed null at assignment/return/arg/comparison boundaries. Runtime null-dereference checks reuse the array-bounds-check abort pattern (compare → error block → `printf` + `exit(1)`).

**Tech Stack:** Python 3.11+, llvmlite (LLVM IR + MCJIT). Tests run `tawlac` as a subprocess (see `tests/conftest.py`'s `run_twl`) for behavior, and call `tokenize`/`parse`/`check` directly for unit-level checks.

**Reference spec:** `docs/superpowers/specs/2026-06-01-null-and-default-values-design.md`

**Milestone:** M25 — ships as 0.4.0 (additive, non-breaking). The release itself is a separate user-triggered step, not part of this plan.

---

## File structure

- `tawla/tokens.py` — add `KW_NULL` token + `"null"` keyword.
- `tawla/ast_nodes.py` — add `NullLiteral(Expr)`; make `VarDecl.init` optional.
- `tawla/parser.py` — parse `null` in `primary`; make the initializer optional in `_finish_var`.
- `tawla/sema.py` — `NULL` type, null typing/assignability, uninitialized-decl defaults, null comparisons, value-type errors.
- `tawla/monomorphize.py` — keep `init=None` instead of transforming a missing initializer.
- `tawla/codegen.py` — null sentinel type, null value gen, coercion, default-init, null comparisons, runtime null-deref checks.
- `tests/test_m25.py` — new test file (built up across tasks).
- `examples/nullable.twl` — example.
- `README.md` — feature bullet.

---

## Task 1: `null` literal — token, AST node, parser

**Files:**
- Modify: `tawla/tokens.py`
- Modify: `tawla/ast_nodes.py`
- Modify: `tawla/parser.py`
- Test: `tests/test_m25.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_m25.py`:

```python
"""M25: null and default-initialized variables."""

import pytest

from tawla.ast_nodes import NullLiteral, PrintStmt
from tawla.lexer import tokenize
from tawla.parser import parse
from tawla.tokens import TokenKind


def test_null_lexes_as_keyword():
    assert tokenize("null")[0].kind is TokenKind.KW_NULL


def test_null_parses_to_null_literal():
    items = parse(tokenize("print(null);"))
    assert isinstance(items[0], PrintStmt)
    assert isinstance(items[0].expr, NullLiteral)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m25.py -q`
Expected: FAIL — `AttributeError: KW_NULL` / `ImportError: cannot import name 'NullLiteral'`.

- [ ] **Step 3: Add the token**

In `tawla/tokens.py`, add `KW_NULL` to the `TokenKind` enum (next to the other keyword kinds, e.g. after `KW_FALSE`):

```python
    KW_FALSE = auto()
    KW_NULL = auto()
```

And add to the `KEYWORDS` dict:

```python
    "false": TokenKind.KW_FALSE,
    "null": TokenKind.KW_NULL,
```

- [ ] **Step 4: Add the AST node**

In `tawla/ast_nodes.py`, after `IntLiteral` / `FloatLiteral`:

```python
@dataclass
class NullLiteral(Expr):
    pass
```

- [ ] **Step 5: Parse it**

In `tawla/parser.py`, add `NullLiteral` to the imports from `.ast_nodes`. In `primary()`, after the `KW_FALSE` case and before `KW_THIS`:

```python
        if tok.kind is TokenKind.KW_NULL:
            self.advance()
            return NullLiteral()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m25.py -q`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add tawla/tokens.py tawla/ast_nodes.py tawla/parser.py tests/test_m25.py
git commit -m "Add null literal token, AST node, and parsing"
```

---

## Task 2: Optional initializers + monomorphize guard

**Files:**
- Modify: `tawla/ast_nodes.py`
- Modify: `tawla/parser.py:194-198` (`_finish_var`)
- Modify: `tawla/monomorphize.py` (`xf_stmt`, `VarDecl` branch)
- Test: `tests/test_m25.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_m25.py`:

```python
from tawla.ast_nodes import VarDecl
from tawla.monomorphize import monomorphize


def test_typed_decl_without_initializer_parses():
    items = parse(tokenize("int x;"))
    assert isinstance(items[0], VarDecl)
    assert items[0].init is None


def test_decl_with_initializer_still_parses():
    items = parse(tokenize("int x = 5;"))
    assert isinstance(items[0], VarDecl)
    assert items[0].init is not None


def test_monomorphize_keeps_none_init():
    src = (
        "class Box<T> { T v; }"
        " class Main { void main() { int x; Box<int> b = new Box<int>(); } }"
    )
    monomorphize(parse(tokenize(src)))  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m25.py -q`
Expected: FAIL — `test_typed_decl_without_initializer_parses` raises `ParseError` (expects `=`), and `test_monomorphize_keeps_none_init` raises inside `xf_expr(None)`.

- [ ] **Step 3: Make `VarDecl.init` optional in the AST**

In `tawla/ast_nodes.py`, change the `VarDecl` dataclass:

```python
@dataclass
class VarDecl(Stmt):
    var_type: str
    name: str
    init: Expr | None
```

- [ ] **Step 4: Make the initializer optional in the parser**

In `tawla/parser.py`, replace `_finish_var`:

```python
    def _finish_var(self, var_type: str, name: str) -> Stmt:
        if self.current.kind is TokenKind.ASSIGN:
            self.advance()
            init = self.expr()
        else:
            init = None
        self.expect(TokenKind.SEMICOLON)
        return VarDecl(var_type, name, init)
```

(`var x;` with no initializer still parses here; sema rejects it in Task 3 with a clear message.)

- [ ] **Step 5: Guard monomorphize against a missing initializer**

In `tawla/monomorphize.py`, in `xf_stmt`, replace the `VarDecl` branch:

```python
        if isinstance(s, VarDecl):
            vt = s.var_type if s.var_type == "var" else self.xf_type(s.var_type, subst)
            init = None if s.init is None else self.xf_expr(s.init, subst)
            return replace(s, var_type=vt, init=init)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m25.py -q`
Expected: PASS (5 passed).

- [ ] **Step 7: Run the full suite (no regressions)**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS (all existing tests still green).

- [ ] **Step 8: Commit**

```bash
git add tawla/ast_nodes.py tawla/parser.py tawla/monomorphize.py tests/test_m25.py
git commit -m "Allow declarations without an initializer"
```

---

## Task 3: Sema — null type, assignability, defaults, comparisons

**Files:**
- Modify: `tawla/sema.py`
- Test: `tests/test_m25.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_m25.py`:

```python
from tawla.sema import SemaError, check


def _sema(src):
    return check(parse(tokenize(src)))


def test_null_assignable_to_class():
    _sema("class A {} class Main { void main() { A a = null; } }")


def test_null_assignable_to_string_and_array():
    _sema("class Main { void main() { string s = null; int[] a = null; } }")


def test_null_not_assignable_to_int():
    with pytest.raises(SemaError):
        _sema("class Main { void main() { int x = null; } }")


def test_var_assigned_null_is_error():
    with pytest.raises(SemaError):
        _sema("class Main { void main() { var z = null; } }")


def test_uninitialized_typed_decls_ok():
    _sema("class A {} class Main { void main() { int x; bool b; string s; A a; } }")


def test_uninitialized_var_is_error():
    with pytest.raises(SemaError):
        _sema("class Main { void main() { var z; } }")


def test_compare_reference_to_null_ok():
    _sema("class A {} class Main { void main() { A a = null; if (a == null) {} } }")


def test_compare_int_to_null_is_error():
    with pytest.raises(SemaError):
        _sema("class Main { void main() { int x = 0; if (x == null) {} } }")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m25.py -k "sema or null_assignable or uninit or compare or var_assigned" -q`
Expected: FAIL — e.g. `test_null_assignable_to_class` raises `SemaError: cannot type-check expression NullLiteral`.

- [ ] **Step 3: Add the NULL type and import NullLiteral/For-style imports**

In `tawla/sema.py`, add `NullLiteral` to the imports from `.ast_nodes`. After the existing `VOID = Type("void")` and `_NUMERIC = {INT, FLOAT}` block, add:

```python
NULL = Type("null")
```

- [ ] **Step 4: Add a reference-type helper and the NULL subtype rule**

In `tawla/sema.py`, add a helper method to the `Sema` class (near `_is_subtype`):

```python
    def _is_reference(self, t: Type) -> bool:
        """True for types that can hold null: string, arrays, classes, interfaces."""
        if t == STRING:
            return True
        if t.name.endswith("[]"):
            return True
        return t.name in self.classes or t.name in self.interfaces
```

In `_is_subtype`, add the NULL rule right after the `if sub == INT and sup == FLOAT:` line:

```python
        if sub == NULL:
            return self._is_reference(sup)
```

- [ ] **Step 5: Type the null literal**

In `_check_expr`, after the `IntLiteral`/`FloatLiteral` cases:

```python
        if isinstance(node, NullLiteral):
            return NULL
```

- [ ] **Step 6: Handle uninitialized declarations**

In `_check_stmt`, at the very start of the `VarDecl` branch (before `init_type = self._check_expr(stmt.init)`), handle the no-initializer case:

```python
        if isinstance(stmt, VarDecl):
            if stmt.init is None:
                if stmt.var_type == "var":
                    raise SemaError(
                        f"variable {stmt.name!r} declared with 'var' needs an initializer"
                    )
                declared = self._type_from_name(stmt.var_type)
                if stmt.name in self.scope:
                    raise SemaError(f"variable {stmt.name!r} already declared")
                self.scope[stmt.name] = declared
                return
            init_type = self._check_expr(stmt.init)
            ...  # existing body unchanged
```

(The `var z = null;` error comes for free: `init` is a `NullLiteral` → `NULL`, `stmt.var_type == "var"` so `declared = NULL`, and `NULL` is not a valid declared type — but to give a clear message, also guard it: in the existing `var` inference branch, after `declared = init_type`, add `if declared == NULL: raise SemaError("cannot infer a type from null")`.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m25.py -q`
Expected: PASS (all M25 tests so far).

- [ ] **Step 8: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add tawla/sema.py tests/test_m25.py
git commit -m "Type-check null and uninitialized declarations"
```

---

## Task 4: Codegen — null value, coercion, defaults, comparisons

**Files:**
- Modify: `tawla/codegen.py`
- Test: `tests/test_m25.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_m25.py`:

```python
def test_null_equality_true(run_twl):
    src = (
        "class A {} class Main { void main() {"
        " A a = null; if (a == null) { print(1); } else { print(2); } } }"
    )
    assert run_twl(src).stdout == "1\n"


def test_reassign_makes_not_null(run_twl):
    src = (
        "class A { int x; } class Main { void main() {"
        " A a = null; a = new A(); if (a != null) { print(1); } } }"
    )
    assert run_twl(src).stdout == "1\n"


def test_default_int_is_zero(run_twl):
    assert run_twl("class Main { void main() { int x; print(x); } }").stdout == "0\n"


def test_default_bool_is_false(run_twl):
    src = "class Main { void main() { bool b; if (b) { print(1); } else { print(0); } } }"
    assert run_twl(src).stdout == "0\n"


def test_default_float_is_zero(run_twl):
    assert run_twl("class Main { void main() { float f; print(f); } }").stdout == "0\n"


def test_object_field_defaults_to_null(run_twl):
    src = (
        "class Node { Node next; }"
        " class Main { void main() { Node n = new Node(); if (n.next == null) { print(1); } } }"
    )
    assert run_twl(src).stdout == "1\n"


def test_null_string_compares_equal(run_twl):
    src = "class Main { void main() { string s; if (s == null) { print(1); } } }"
    assert run_twl(src).stdout == "1\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m25.py -k "null_equality or reassign or default_ or object_field or null_string_compares" -q`
Expected: FAIL — codegen raises `CodeGenError: cannot codegen expression NullLiteral`.

- [ ] **Step 3: Import NullLiteral and create the null sentinel + message**

In `tawla/codegen.py`, add `NullLiteral` to the imports from `.ast_nodes`. In `_declare_runtime` (which already has access to `self.module`), add near the format-string definitions:

```python
        self.null_ty = self.module.context.get_identified_type("$null")  # stays opaque
        self.null_ptr = self.null_ty.as_pointer()
        self._null_msg = self._global_string(b"null reference\n\0", "null_msg")
```

- [ ] **Step 4: Generate the null literal**

In `_gen_expr`, after the `IntLiteral`/`FloatLiteral` cases:

```python
        if isinstance(node, NullLiteral):
            return ir.Constant(self.null_ptr, None)
```

- [ ] **Step 5: Teach `_coerce` to turn the sentinel into a typed null**

In `_coerce`, right after the `if value.type == target_ty: return value` line:

```python
        if value.type == self.null_ptr:
            if isinstance(target_ty, ir.IdentifiedStructType) and target_ty.name in self.iface_struct:
                return ir.Constant(target_ty, None)   # zero-initialized fat pointer
            if isinstance(target_ty, ir.PointerType):
                return ir.Constant(target_ty, None)   # typed null pointer
            return value
```

- [ ] **Step 6: Extend `_zero` to cover struct (interface) types**

Replace the `_zero` static method:

```python
    @staticmethod
    def _zero(ty: ir.Type) -> ir.Constant:
        if isinstance(ty, ir.PointerType):
            return ir.Constant(ty, None)
        if isinstance(ty, (ir.IdentifiedStructType, ir.LiteralStructType)):
            return ir.Constant(ty, None)   # zeroinitializer
        return ir.Constant(ty, 0)
```

- [ ] **Step 7: Default-initialize declarations without an initializer**

In `_gen_stmt`, replace the `VarDecl` branch:

```python
        if isinstance(stmt, VarDecl):
            if stmt.name in self.symbols:
                raise CodeGenError(f"variable {stmt.name!r} already declared")
            slot_ty = self._llvm_type(stmt.var_type)
            if stmt.init is None:
                value = self._zero(slot_ty)
            else:
                value = self._coerce(self._gen_expr(stmt.init), slot_ty)
            slot = self._alloca(stmt.name, slot_ty)
            self.builder.store(value, slot)
            self.symbols[stmt.name] = slot
            self._maybe_root(slot)
            return
```

- [ ] **Step 8: Handle null in `==`/`!=`**

In `_gen_expr`, in the `BinaryOp` branch, immediately after `left = ...` / `right = ...` are generated and **before** the `if left.type == i8ptr:` string check, add:

```python
            if node.op in ("==", "!=") and (
                left.type == self.null_ptr or right.type == self.null_ptr
            ):
                return self._gen_null_compare(node.op, left, right)
```

Then add the helper method (near `_gen_float_binop`):

```python
    def _gen_null_compare(self, op: str, left: ir.Value, right: ir.Value) -> ir.Value:
        if left.type == self.null_ptr and right.type == self.null_ptr:
            return ir.Constant(i1, 1 if op == "==" else 0)
        ref = right if left.type == self.null_ptr else left
        if isinstance(ref.type, ir.IdentifiedStructType) and ref.type.name in self.iface_struct:
            obj = self.builder.extract_value(ref, 0)
            return self.builder.icmp_signed(op, obj, ir.Constant(i8ptr, None))
        return self.builder.icmp_signed(op, ref, ir.Constant(ref.type, None))
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m25.py -q`
Expected: PASS.

- [ ] **Step 10: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add tawla/codegen.py tests/test_m25.py
git commit -m "Codegen for null values, defaults, and null comparisons"
```

---

## Task 5: Codegen — runtime null-dereference checks

**Files:**
- Modify: `tawla/codegen.py`
- Test: `tests/test_m25.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_m25.py`:

```python
def _err(result):
    return result.stdout + result.stderr


def test_method_call_on_null_aborts(run_twl):
    src = "class A { void hi() {} } class Main { void main() { A a = null; a.hi(); } }"
    r = run_twl(src)
    assert r.returncode != 0
    assert "null reference" in _err(r)


def test_field_access_on_null_aborts(run_twl):
    src = "class A { int x; } class Main { void main() { A a = null; print(a.x); } }"
    r = run_twl(src)
    assert r.returncode != 0
    assert "null reference" in _err(r)


def test_index_on_null_aborts(run_twl):
    src = "class Main { void main() { int[] a; print(a[0]); } }"
    r = run_twl(src)
    assert r.returncode != 0
    assert "null reference" in _err(r)


def test_length_on_null_aborts(run_twl):
    src = "class Main { void main() { int[] a; print(a.length); } }"
    r = run_twl(src)
    assert r.returncode != 0
    assert "null reference" in _err(r)


def test_print_null_string_aborts(run_twl):
    src = "class Main { void main() { string s; print(s); } }"
    r = run_twl(src)
    assert r.returncode != 0
    assert "null reference" in _err(r)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m25.py -k "aborts" -q`
Expected: FAIL — programs currently segfault / exit 0 / crash instead of printing "null reference".

- [ ] **Step 3: Add the null-check helper**

In `tawla/codegen.py`, add (near `_bounds_check`, which it mirrors):

```python
    def _null_check(self, ptr: ir.Value) -> None:
        """Abort with 'null reference' if `ptr` is null. `ptr` must be a pointer."""
        is_null = self.builder.icmp_signed("==", ptr, ir.Constant(ptr.type, None))
        func = self.builder.function
        err_bb = func.append_basic_block("null.err")
        ok_bb = func.append_basic_block("null.ok")
        self.builder.cbranch(is_null, err_bb, ok_bb)

        self.builder.position_at_end(err_bb)
        self.builder.call(self.printf, [self._str_ptr(self._null_msg)])
        self.builder.call(self.exit, [ir.Constant(i32, 1)])
        self.builder.unreachable()

        self.builder.position_at_end(ok_bb)
```

- [ ] **Step 4: Check the receiver of a method call**

In `_gen_method_call`, after `obj = self._gen_expr(node.obj)`, before the interface/vtable branching:

```python
        obj = self._gen_expr(node.obj)
        if isinstance(obj.type, ir.IdentifiedStructType) and obj.type.name in self.iface_struct:
            self._null_check(self.builder.extract_value(obj, 0))
            return self._gen_interface_call(node, obj)
        self._null_check(obj)
        static_class = obj.type.pointee.name
        ...  # rest unchanged
```

- [ ] **Step 5: Check field access (read + write) and `.length`**

In `_class_field_ptr`, add a null-check at the top (covers both reads via `_gen_expr` and writes via `Assign`):

```python
    def _class_field_ptr(self, obj: ir.Value, field: str) -> ir.Value:
        self._null_check(obj)
        class_name = obj.type.pointee.name
        ...  # rest unchanged
```

In `_gen_expr`'s `FieldAccess` branch, add a null-check before the `.length` reads for string and array. The branch currently begins:

```python
        if isinstance(node, FieldAccess):
            obj = self._gen_expr(node.obj)
            if obj.type == i8ptr:
                self._null_check(obj)
                return self.builder.trunc(self.builder.call(self.strlen, [obj]), i32)
            if isinstance(obj.type.pointee, ir.LiteralStructType):
                self._null_check(obj)
                len_ptr = self.builder.gep(...)
                ...
            return self.builder.load(self._class_field_ptr(obj, node.field))
```

(The class-field path already goes through `_class_field_ptr`, which now null-checks, so only the two `.length` branches need the explicit call.)

- [ ] **Step 6: Check array indexing (read + write)**

In `_index_ptr`, after `arr = self._gen_expr(node.arr)`:

```python
    def _index_ptr(self, node: Index) -> ir.Value:
        arr = self._gen_expr(node.arr)
        self._null_check(arr)
        idx = self._gen_expr(node.index)
        ...  # rest unchanged
```

- [ ] **Step 7: Check `print` of a null string**

In `_gen_stmt`'s `PrintStmt` branch, add a null-check in the string case:

```python
        if isinstance(stmt, PrintStmt):
            value = self._gen_expr(stmt.expr)
            if value.type == i8ptr:
                self._null_check(value)
                fmt = self._fmt_str
            elif value.type == f64:
                ...  # unchanged
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m25.py -q`
Expected: PASS.

- [ ] **Step 9: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS (existing array/interface/method tests still green — the null checks are transparent for non-null values).

- [ ] **Step 10: Commit**

```bash
git add tawla/codegen.py tests/test_m25.py
git commit -m "Runtime null-reference checks on dereferences"
```

---

## Task 6: Example, README, final verification

**Files:**
- Create: `examples/nullable.twl`
- Modify: `README.md`

- [ ] **Step 1: Write the example**

Create `examples/nullable.twl`:

```tawla
// null lets a reference be "absent", and declarations can skip the initializer
// (defaulting to 0 / false / null).

class Account {
    int balance;
}

class Main {
    void main() {
        Account a;                  // no initializer -> null
        if (a == null) {
            print("no account yet");
        }

        a = new Account();          // balance defaults to 0
        print(a.balance);           // 0

        int count;                  // defaults to 0
        print(count);               // 0
    }
}
```

- [ ] **Step 2: Run the example**

Run: `./venv/Scripts/python -m tawla run examples/nullable.twl`
Expected output:
```
no account yet
0
0
```

- [ ] **Step 3: Add a README bullet**

In `README.md`, under "What the language can do", add after the `var` bullet:

```markdown
- **`null` & defaults:** reference types (objects, strings, arrays) can be
  `null`, and a declaration can skip the initializer — `int x;` is `0`,
  `bool b;` is `false`, `User u;` is `null`. Using a `null` (calling a method,
  reading a field, indexing) gives a clean "null reference" error instead of a
  crash. Value types (`int`, `float`, `bool`) can't be null.
```

- [ ] **Step 4: Full suite + example sanity**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add examples/nullable.twl README.md
git commit -m "Add null example and README note"
```

---

## Self-review

**Spec coverage:**
- `null` literal + keyword → Task 1. ✓
- Assignable only to reference types; not value types → Task 3 (`_is_reference`, NULL subtype rule; `int x = null` error). ✓
- `==`/`!= null`, value-vs-null error → Task 3 (sema) + Task 4 (codegen `_gen_null_compare`). ✓
- Optional initializers with zero/null defaults; `var` without init errors → Task 2 (parser) + Task 3 (sema) + Task 4 (codegen `_zero`/default-init). ✓
- Runtime null-deref errors on method call, field access, indexing, `.length`, print-null-string → Task 5. ✓
- Null sentinel type so null ≠ string → Task 4 (`null_ptr`). ✓
- monomorphize handles `init=None` → Task 2. ✓
- No static null-safety (out of scope) → not implemented, as intended. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code; commands have expected output. ✓

**Type consistency:** `self.null_ptr` / `self.null_ty` / `self._null_msg` defined in Task 4 Step 3 and used consistently in Tasks 4–5. `_null_check`, `_gen_null_compare`, `_is_reference`, `_zero`, `NULL` names match across tasks. `VarDecl.init: Expr | None` defined Task 2, relied on in Tasks 3–4. ✓
