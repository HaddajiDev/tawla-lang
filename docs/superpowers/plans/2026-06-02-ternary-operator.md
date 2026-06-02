# Ternary Operator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the conditional expression `cond ? a : b` (lowest precedence, right-associative, lazy, common-branch-type result).

**Architecture:** A `?` token + a new `ternary` parser level above `logic_or` producing a `Ternary` AST node; sema requires a bool condition and computes the common branch type (reusing `_is_subtype`); codegen lowers it like an `if`-expression with a result slot so only the taken branch is evaluated.

**Tech Stack:** Python 3.11+, llvmlite. Compile-time checks via `tokenize`/`parse`/`check`; runtime via the `run_twl` subprocess fixture.

**Reference spec:** `docs/superpowers/specs/2026-06-02-ternary-operator-design.md`

**Milestone:** M29 — additive; bundles with logical operators into **1.2.0** (release is a separate user-triggered step).

---

## File structure

- `tawla/tokens.py` — add `QUESTION`.
- `tawla/lexer.py` — map `?` in the single-char table.
- `tawla/ast_nodes.py` — add `Ternary`.
- `tawla/parser.py` — `ternary` level; `expr` enters at it.
- `tawla/monomorphize.py` — traverse `Ternary`.
- `tawla/sema.py` — type-check `Ternary`.
- `tawla/codegen.py` — lower `Ternary`.
- `tests/test_m29.py` — new tests.
- `examples/ternary.twl`, `README.md` — example + note.

---

## Task 1: Token, AST, parser, monomorphize

**Files:**
- Modify: `tawla/tokens.py`, `tawla/lexer.py`, `tawla/ast_nodes.py`, `tawla/parser.py`, `tawla/monomorphize.py`
- Test: `tests/test_m29.py`

- [ ] **Step 1: Write the failing tests** — Create `tests/test_m29.py`:

```python
"""M29: ternary operator (cond ? a : b)."""

import pytest

from tawla.ast_nodes import Ternary
from tawla.lexer import tokenize
from tawla.monomorphize import monomorphize
from tawla.parser import parse
from tawla.tokens import TokenKind


def _expr(src):
    from tawla.ast_nodes import PrintStmt
    stmt = parse(tokenize("print(" + src + ");"))[0]
    assert isinstance(stmt, PrintStmt)
    return stmt.expr


def test_question_lexes():
    assert tokenize("?")[0].kind is TokenKind.QUESTION


def test_ternary_parses():
    e = _expr("a ? b : c")
    assert isinstance(e, Ternary)


def test_ternary_is_right_associative():
    # a ? b : c ? d : e  ->  a ? b : (c ? d : e)
    e = _expr("a ? b : c ? d : e")
    assert isinstance(e, Ternary)
    assert isinstance(e.else_expr, Ternary)


def test_ternary_lower_precedence_than_or():
    # p || q ? x : y  ->  (p || q) ? x : y
    from tawla.ast_nodes import BinaryOp
    e = _expr("p || q ? x : y")
    assert isinstance(e, Ternary)
    assert isinstance(e.cond, BinaryOp) and e.cond.op == "||"


def test_monomorphize_traverses_ternary():
    src = (
        "class Box<T> { public T v; }"
        " class Main { void main() { bool t = true; int x = t ? 1 : 2;"
        " var b = new Box<int>(); } }"
    )
    monomorphize(parse(tokenize(src)))  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m29.py -q`
Expected: FAIL — `ImportError: Ternary` / `AttributeError: QUESTION`.

- [ ] **Step 3: Add the token** — In `tawla/tokens.py`, add to `TokenKind` (near `COLON`):

```python
    QUESTION = auto()
```

- [ ] **Step 4: Lex `?`** — In `tawla/lexer.py`, add to the `_SINGLE` dict (next to `":"`):

```python
    "?": TokenKind.QUESTION,
```

- [ ] **Step 5: Add the AST node** — In `tawla/ast_nodes.py`, after `BinaryOp`:

```python
@dataclass
class Ternary(Expr):
    cond: Expr
    then_expr: Expr
    else_expr: Expr
    result_type: str | None = None
```

- [ ] **Step 6: Parse the ternary** — In `tawla/parser.py`, add `Ternary` to the `.ast_nodes` imports. Replace `expr` and add `ternary`:

```python
    def expr(self) -> Expr:
        return self.ternary()

    def ternary(self) -> Expr:
        cond = self.logic_or()
        if self.current.kind is TokenKind.QUESTION:
            self.advance()
            then_expr = self.expr()
            self.expect(TokenKind.COLON)
            else_expr = self.ternary()
            return Ternary(cond, then_expr, else_expr)
        return cond
```

Update the grammar comment: change `expr := logic_or` to:

```
    expr       := ternary
    ternary    := logic_or ('?' expr ':' ternary)?
```

- [ ] **Step 7: Traverse in monomorphize** — In `tawla/monomorphize.py`, add `Ternary` to the `.ast_nodes` imports, and in `xf_expr` add (before the final `return e`):

```python
        if isinstance(e, Ternary):
            return replace(
                e,
                cond=self.xf_expr(e.cond, subst),
                then_expr=self.xf_expr(e.then_expr, subst),
                else_expr=self.xf_expr(e.else_expr, subst),
            )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m29.py -q`
Expected: PASS (5 passed).

- [ ] **Step 9: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS (existing expressions unaffected — `expr` still reaches `logic_or`).

- [ ] **Step 10: Commit**

```bash
git add tawla/tokens.py tawla/lexer.py tawla/ast_nodes.py tawla/parser.py tawla/monomorphize.py tests/test_m29.py
git commit -m "Parse ternary operator into a Ternary node"
```

---

## Task 2: Sema — condition + common branch type

**Files:**
- Modify: `tawla/sema.py`
- Test: `tests/test_m29.py`

- [ ] **Step 1: Write the failing tests** — Append to `tests/test_m29.py`:

```python
from tawla.sema import SemaError, check


def _sema(src):
    return check(parse(tokenize(src)))


def test_ternary_typechecks_ok():
    _sema("class Main { void main() { int x = true ? 1 : 2; } }")


def test_ternary_int_float_common_type_is_float():
    # assigning to a float is fine; assigning the int/float mix to int is not
    _sema("class Main { void main() { float x = true ? 1 : 2.0; } }")
    with pytest.raises(SemaError):
        _sema("class Main { void main() { int x = true ? 1 : 2.0; } }")


def test_ternary_condition_must_be_bool():
    with pytest.raises(SemaError):
        _sema("class Main { void main() { int x = 5 ? 1 : 2; } }")


def test_ternary_incompatible_branches_error():
    with pytest.raises(SemaError):
        _sema('class Main { void main() { var x = true ? 1 : "s"; } }')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m29.py -q -k "typecheck or common_type or condition_must or incompatible"`
Expected: FAIL — `SemaError: cannot type-check expression Ternary`.

- [ ] **Step 3: Type-check `Ternary`** — In `tawla/sema.py`, add `Ternary` to the `.ast_nodes` imports, and in `_check_expr` add a branch (near the `BinaryOp` handling):

```python
        if isinstance(node, Ternary):
            if self._check_expr(node.cond) != BOOL:
                raise SemaError("ternary condition must be bool")
            t1 = self._check_expr(node.then_expr)
            t2 = self._check_expr(node.else_expr)
            if t1 == VOID or t2 == VOID:
                raise SemaError("ternary branches cannot be void")
            if self._is_subtype(t2, t1):
                common = t1
            elif self._is_subtype(t1, t2):
                common = t2
            else:
                raise SemaError(
                    f"ternary branches have incompatible types {t1} and {t2}"
                )
            if common == NULL:
                raise SemaError("ternary needs at least one typed branch")
            node.result_type = common.name
            return common
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m29.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tawla/sema.py tests/test_m29.py
git commit -m "Type-check ternary (bool condition, common branch type)"
```

---

## Task 3: Codegen — if-style lowering

**Files:**
- Modify: `tawla/codegen.py`
- Test: `tests/test_m29.py`

- [ ] **Step 1: Write the failing tests** — Append to `tests/test_m29.py`:

```python
def test_ternary_selects_then(run_twl):
    assert run_twl("class Main { void main() { print(true ? 1 : 2); } }").stdout == "1\n"


def test_ternary_selects_else(run_twl):
    assert run_twl("class Main { void main() { print(false ? 1 : 2); } }").stdout == "2\n"


def test_ternary_int_float_runs_as_float(run_twl):
    # 7/2 int is 3; (true ? 7 : 0) / 2.0 forces float division -> 3.5
    src = "class Main { void main() { print((true ? 7 : 0) / 2.0); } }"
    assert run_twl(src).stdout == "3.5\n"


def test_ternary_nesting(run_twl):
    src = (
        "int label(int n) { return n == 0 ? 10 : n == 1 ? 20 : 30; }"
        " class Main { void main() { print(label(0)); print(label(1)); print(label(2)); } }"
    )
    assert run_twl(src).stdout == "10\n20\n30\n"


def test_ternary_is_lazy(run_twl):
    # a is null; the then-branch (a.v()) must not be evaluated when cond is false.
    src = (
        "class A { public int v() { return 1; } }"
        " class Main { void main() {"
        " A a = null; int id = a != null ? a.v() : 0; print(id); } }"
    )
    r = run_twl(src)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout == "0\n"


def test_ternary_with_objects(run_twl):
    # both branches are objects; result assigned through the common type
    src = (
        "class A { public int who() { return 1; } }"
        " class Main { void main() {"
        " A x = new A(); A y = new A(); A z = true ? x : y; print(z.who()); } }"
    )
    assert run_twl(src).stdout == "1\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m29.py -q -k "selects or runs_as_float or nesting or lazy or with_objects"`
Expected: FAIL — `CodeGenError: cannot codegen expression Ternary`.

- [ ] **Step 3: Lower `Ternary`** — In `tawla/codegen.py`, add `Ternary` to the `.ast_nodes` imports, and in `_gen_expr` add a branch:

```python
        if isinstance(node, Ternary):
            slot_ty = self._llvm_type(node.result_type)
            slot = self._alloca("ternary", slot_ty)
            cond = self._as_bool(self._gen_expr(node.cond))
            func = self.builder.function
            then_bb = func.append_basic_block("ternary.then")
            else_bb = func.append_basic_block("ternary.else")
            end_bb = func.append_basic_block("ternary.end")
            self.builder.cbranch(cond, then_bb, else_bb)

            self.builder.position_at_end(then_bb)
            self.builder.store(self._coerce(self._gen_expr(node.then_expr), slot_ty), slot)
            self.builder.branch(end_bb)

            self.builder.position_at_end(else_bb)
            self.builder.store(self._coerce(self._gen_expr(node.else_expr), slot_ty), slot)
            self.builder.branch(end_bb)

            self.builder.position_at_end(end_bb)
            return self.builder.load(slot)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m29.py -q`
Expected: PASS (all M29 tests).

- [ ] **Step 5: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tawla/codegen.py tests/test_m29.py
git commit -m "Codegen for the ternary operator"
```

---

## Task 4: Example, README, final verification

**Files:**
- Create: `examples/ternary.twl`
- Modify: `README.md`

- [ ] **Step 1: Write the example** — Create `examples/ternary.twl`:

```tawla
// The ternary operator: cond ? a : b  (lazy, picks a common branch type).

int max(int a, int b) {
    return a > b ? a : b;
}

class Main {
    void main() {
        print(max(3, 9));                      // 9

        int n = 2;
        string size = n == 0 ? "zero" : n < 10 ? "small" : "big";
        print(size);                           // small
    }
}
```

- [ ] **Step 2: Run the example**

Run: `./venv/Scripts/python -m tawla run examples/ternary.twl`
Expected output:
```
9
small
```

- [ ] **Step 3: Add a README bullet** — In `README.md`, under "What the language can do", after the logical-operators bullet:

```markdown
- **Ternary:** `cond ? a : b` picks a value inline (lazy — only the taken
  branch runs).
```

- [ ] **Step 4: Final full-suite run**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add examples/ternary.twl README.md
git commit -m "Add ternary example and README note"
```

---

## Self-review

**Spec coverage:**
- `?` token + lexing → Task 1. ✓
- `Ternary` node + parse, lowest precedence, right-associative → Task 1 (`ternary` enters from `expr`, else-branch recurses) + precedence/right-assoc tests. ✓
- bool condition; common branch type via `_is_subtype`; incompatible/void/all-null errors → Task 2. ✓
- lazy evaluation (only taken branch) → Task 3 (`if`-style blocks) + `test_ternary_is_lazy`. ✓
- `result_type` annotated by sema, read by codegen → Task 2 sets `node.result_type`; Task 3 uses `_llvm_type(node.result_type)`. ✓
- monomorphize traverses `Ternary` → Task 1 + `test_monomorphize_traverses_ternary`. ✓
- Testing (selection, type rules, lazy, nesting, precedence, sema errors) → Tasks 1–3. ✓
- Example + README → Task 4. ✓

**Placeholder scan:** No TBD/TODO; every code/test step shows full content; commands have expected output.

**Type consistency:** `QUESTION` token consistent across tokens/lexer/parser. `Ternary(cond, then_expr, else_expr, result_type)` field names match across parser (construct), sema (`node.cond`/`then_expr`/`else_expr`, sets `result_type`), codegen (reads `result_type`, `then_expr`, `else_expr`), and monomorphize. Codegen uses `_as_bool`/`_coerce`/`_llvm_type`/`_alloca` — all existing helpers. ✓
