# Logical Operators (&&, ||, !) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add boolean `&&`, `||`, and `!` with C-style precedence and short-circuit evaluation.

**Architecture:** New tokens + lexer cases; two parser precedence levels (`logic_or` → `logic_and`) above comparison, with `!` joining unary `-` at the `factor` level; sema requires bool operands and yields bool; codegen emits `xor` for `!` and short-circuiting basic blocks for `&&`/`||`.

**Tech Stack:** Python 3.11+, llvmlite. Compile-time checks via `tokenize`/`parse`/`check`; runtime via the `run_twl` subprocess fixture.

**Reference spec:** `docs/superpowers/specs/2026-06-02-logical-operators-design.md`

**Milestone:** M28 — additive, ships as **1.2.0** (release is a separate user-triggered step).

---

## File structure

- `tawla/tokens.py` — `AND` / `OR` / `NOT` token kinds.
- `tawla/lexer.py` — lex `&&`, `||`, and bare `!`.
- `tawla/parser.py` — `logic_or`/`logic_and` levels; `!` in `factor`.
- `tawla/sema.py` — bool typing for `&&`/`||`/`!`.
- `tawla/codegen.py` — `!` via `xor`; short-circuit `&&`/`||`.
- `tests/test_m28.py` — new tests.
- `examples/logic.twl`, `README.md` — example + note.

---

## Task 1: Tokens + lexer

**Files:**
- Modify: `tawla/tokens.py`
- Modify: `tawla/lexer.py`
- Test: `tests/test_m28.py`

- [ ] **Step 1: Write the failing tests** — Create `tests/test_m28.py`:

```python
"""M28: logical operators (&&, ||, !)."""

import pytest

from tawla.lexer import LexError, tokenize
from tawla.tokens import TokenKind


def test_lex_and_or_not():
    kinds = [t.kind for t in tokenize("&& || !")]
    assert kinds[:3] == [TokenKind.AND, TokenKind.OR, TokenKind.NOT]


def test_lex_not_equals_still_works():
    assert tokenize("!=")[0].kind is TokenKind.NE


def test_lex_single_ampersand_is_error():
    with pytest.raises(LexError):
        tokenize("a & b")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m28.py -q`
Expected: FAIL — `AttributeError: AND` / `!` raises "unexpected character".

- [ ] **Step 3: Add the tokens** — In `tawla/tokens.py`, add to `TokenKind` (near the other operators, e.g. after `NE`):

```python
    AND = auto()
    OR = auto()
    NOT = auto()
```

- [ ] **Step 4: Lex the operators** — In `tawla/lexer.py`, the two-char operator block currently handles `=`, `<`, `>`, `!`. Replace the `!` case and add `&`/`|`:

```python
        elif c == "!":
            kind, text = (TokenKind.NE, "!=") if nxt == "=" else (TokenKind.NOT, "!")
        elif c == "&":
            if nxt != "&":
                raise LexError(f"unexpected character '&' at position {i}")
            kind, text = TokenKind.AND, "&&"
        elif c == "|":
            if nxt != "|":
                raise LexError(f"unexpected character '|' at position {i}")
            kind, text = TokenKind.OR, "||"
```

(Place the `elif c == "&":` / `elif c == "|":` branches alongside the existing `elif c == "!":` in the same operator chain, before the `else: kind = text = None` line.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m28.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add tawla/tokens.py tawla/lexer.py tests/test_m28.py
git commit -m "Lex &&, ||, and bare !"
```

---

## Task 2: Parser — precedence levels and `!`

**Files:**
- Modify: `tawla/parser.py`
- Test: `tests/test_m28.py`

- [ ] **Step 1: Write the failing tests** — Append to `tests/test_m28.py`:

```python
from tawla.ast_nodes import BinaryOp, UnaryOp
from tawla.parser import parse


def _expr(src):
    # `print(<expr>);` -> the expr inside
    from tawla.ast_nodes import PrintStmt
    stmt = parse(tokenize("print(" + src + ");"))[0]
    assert isinstance(stmt, PrintStmt)
    return stmt.expr


def test_and_parses():
    e = _expr("a && b")
    assert isinstance(e, BinaryOp) and e.op == "&&"


def test_not_parses():
    e = _expr("!a")
    assert isinstance(e, UnaryOp) and e.op == "!"


def test_precedence_comparison_binds_tighter_than_and():
    # a == b && c == d  ->  (a == b) && (c == d)
    e = _expr("a == b && c == d")
    assert e.op == "&&"
    assert isinstance(e.left, BinaryOp) and e.left.op == "=="
    assert isinstance(e.right, BinaryOp) and e.right.op == "=="


def test_precedence_and_binds_tighter_than_or():
    # a || b && c  ->  a || (b && c)
    e = _expr("a || b && c")
    assert e.op == "||"
    assert isinstance(e.right, BinaryOp) and e.right.op == "&&"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m28.py -q -k "parses or precedence"`
Expected: FAIL — `ParseError` on `&&`/`!`.

- [ ] **Step 3: Add precedence levels** — In `tawla/parser.py`, change `expr` to enter at `logic_or`, and add the two levels:

```python
    def expr(self) -> Expr:
        return self.logic_or()

    def logic_or(self) -> Expr:
        node = self.logic_and()
        while self.current.kind is TokenKind.OR:
            self.advance()
            node = BinaryOp("||", node, self.logic_and())
        return node

    def logic_and(self) -> Expr:
        node = self.comparison()
        while self.current.kind is TokenKind.AND:
            self.advance()
            node = BinaryOp("&&", node, self.comparison())
        return node
```

(Replace the existing one-line `def expr(self): return self.comparison()`. Leave `comparison` and below unchanged.)

- [ ] **Step 4: Add `!` to `factor`** — In `tawla/parser.py`, replace `factor`:

```python
    def factor(self) -> Expr:
        if self.current.kind is TokenKind.MINUS:
            self.advance()
            return UnaryOp("-", self.factor())
        if self.current.kind is TokenKind.NOT:
            self.advance()
            return UnaryOp("!", self.factor())
        return self.postfix()
```

Also update the grammar comment near the top of the file: change `expr := comparison` to:

```
    expr       := logic_or
    logic_or   := logic_and ('||' logic_and)*
    logic_and  := comparison ('&&' comparison)*
```

and `factor := '-' factor | postfix` to `factor := ('-' | '!') factor | postfix`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m28.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS (existing expressions unaffected — `expr` still reaches `comparison`).

- [ ] **Step 7: Commit**

```bash
git add tawla/parser.py tests/test_m28.py
git commit -m "Parse &&/|| precedence levels and unary !"
```

---

## Task 3: Sema — bool typing

**Files:**
- Modify: `tawla/sema.py`
- Test: `tests/test_m28.py`

- [ ] **Step 1: Write the failing tests** — Append to `tests/test_m28.py`:

```python
from tawla.sema import SemaError, check


def _sema(src):
    return check(parse(tokenize(src)))


def test_and_or_not_typecheck_ok():
    _sema("class Main { void main() { bool b = true && false || !true; } }")


def test_and_requires_bool():
    with pytest.raises(SemaError):
        _sema("class Main { void main() { bool b = 1 && 2; } }")


def test_not_requires_bool():
    with pytest.raises(SemaError):
        _sema("class Main { void main() { bool b = !5; } }")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m28.py -q -k "typecheck or requires_bool"`
Expected: FAIL — `&&`/`!` reach the numeric paths and raise the wrong/None result (or `test_and_or_not_typecheck_ok` fails because `&&` isn't handled).

- [ ] **Step 3: Add the `_LOGICAL` set** — In `tawla/sema.py`, near `_ARITHMETIC`/`_ORDERING`/`_EQUALITY`:

```python
_LOGICAL = {"&&", "||"}
```

- [ ] **Step 4: Type-check `&&`/`||`** — In `_check_expr`'s `BinaryOp` branch, add a logical case alongside the existing `_ARITHMETIC`/`_ORDERING`/`_EQUALITY` checks (after `left`/`right` are computed):

```python
            if node.op in _LOGICAL:
                if left != BOOL or right != BOOL:
                    raise SemaError(
                        f"operator {node.op!r} requires bool operands, "
                        f"got {left} and {right}"
                    )
                return BOOL
```

- [ ] **Step 5: Type-check `!`** — In `_check_expr`'s `UnaryOp` branch, handle `!` before the numeric check:

```python
        if isinstance(node, UnaryOp):
            operand = self._check_expr(node.operand)
            if node.op == "!":
                if operand != BOOL:
                    raise SemaError(f"unary '!' requires bool, got {operand}")
                return BOOL
            if operand not in _NUMERIC:
                raise SemaError(f"unary '-' requires int or float, got {operand}")
            return operand
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m28.py -q`
Expected: PASS.

- [ ] **Step 7: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tawla/sema.py tests/test_m28.py
git commit -m "Type-check logical operators as bool"
```

---

## Task 4: Codegen — `!` and short-circuit `&&`/`||`

**Files:**
- Modify: `tawla/codegen.py`
- Test: `tests/test_m28.py`

- [ ] **Step 1: Write the failing tests** — Append to `tests/test_m28.py`:

```python
TRUTH = [
    ("true && true", "1"), ("true && false", "0"),
    ("false && true", "0"), ("false && false", "0"),
    ("true || false", "1"), ("false || false", "0"),
    ("false || true", "1"), ("!true", "0"), ("!false", "1"),
]


@pytest.mark.parametrize("expr,out", TRUTH)
def test_truth_tables(run_twl, expr, out):
    src = "class Main { void main() { if (" + expr + ") { print(1); } else { print(0); } } }"
    assert run_twl(src).stdout == out + "\n"


def test_precedence_runs(run_twl):
    src = "class Main { void main() { if (1 == 1 && 2 == 2) { print(1); } else { print(0); } } }"
    assert run_twl(src).stdout == "1\n"


def test_and_short_circuits(run_twl):
    # a is null; `a != null && a.v() == 1` must NOT call a.v() (would null-deref).
    src = (
        "class A { public int v() { return 1; } }"
        " class Main { void main() {"
        " A a = null; if (a != null && a.v() == 1) { print(2); } else { print(1); } } }"
    )
    r = run_twl(src)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout == "1\n"


def test_or_short_circuits(run_twl):
    # a is null; `a == null || a.v() == 1` must NOT call a.v().
    src = (
        "class A { public int v() { return 1; } }"
        " class Main { void main() {"
        " A a = null; if (a == null || a.v() == 1) { print(1); } } }"
    )
    r = run_twl(src)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout == "1\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m28.py -q -k "truth or short_circuit or precedence_runs"`
Expected: FAIL — codegen doesn't handle `&&`/`||`/`!` (CodeGenError or wrong result / crash).

- [ ] **Step 3: Handle `!` in `UnaryOp`** — In `tawla/codegen.py`, replace the `UnaryOp` branch in `_gen_expr`:

```python
        if isinstance(node, UnaryOp):
            operand = self._gen_expr(node.operand)
            if node.op == "!":
                return self.builder.xor(operand, ir.Constant(i1, 1))
            if operand.type == f64:
                return self.builder.fneg(operand)
            return self.builder.sub(ir.Constant(i32, 0), operand)
```

- [ ] **Step 4: Short-circuit `&&`/`||`** — In `_gen_expr`'s `BinaryOp` branch, intercept the logical ops *before* the operands are eagerly generated. Make the branch start:

```python
        if isinstance(node, BinaryOp):
            if node.op in ("&&", "||"):
                return self._gen_logical(node)
            left = self._gen_expr(node.left)
            right = self._gen_expr(node.right)
            ...  # rest unchanged
```

Then add the helper (near `_gen_float_binop`):

```python
    def _gen_logical(self, node: BinaryOp) -> ir.Value:
        slot = self._alloca("logic", i1)
        left = self._gen_expr(node.left)
        func = self.builder.function
        rhs_bb = func.append_basic_block("logic.rhs")
        short_bb = func.append_basic_block("logic.short")
        end_bb = func.append_basic_block("logic.end")

        if node.op == "&&":
            self.builder.cbranch(left, rhs_bb, short_bb)
            self.builder.position_at_end(short_bb)
            self.builder.store(ir.Constant(i1, 0), slot)
        else:   # "||"
            self.builder.cbranch(left, short_bb, rhs_bb)
            self.builder.position_at_end(short_bb)
            self.builder.store(ir.Constant(i1, 1), slot)
        self.builder.branch(end_bb)

        self.builder.position_at_end(rhs_bb)
        self.builder.store(self._gen_expr(node.right), slot)
        self.builder.branch(end_bb)

        self.builder.position_at_end(end_bb)
        return self.builder.load(slot)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m28.py -q`
Expected: PASS (all M28 tests).

- [ ] **Step 6: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tawla/codegen.py tests/test_m28.py
git commit -m "Codegen for ! and short-circuit && / ||"
```

---

## Task 5: Example, README, final verification

**Files:**
- Create: `examples/logic.twl`
- Modify: `README.md`

- [ ] **Step 1: Write the example** — Create `examples/logic.twl`:

```tawla
// Logical operators: && (and), || (or), ! (not), with short-circuit evaluation.

int classify(int n) {
    if (n >= 0 && n <= 9) { return 1; }   // single digit
    if (n < 0 || n > 100) { return 2; }   // out of range
    return 3;
}

class Main {
    void main() {
        print(classify(5));      // 1
        print(classify(-4));     // 2
        print(classify(50));     // 3

        bool ready = true;
        if (!ready) { print(0); } else { print(1); }   // 1
    }
}
```

- [ ] **Step 2: Run the example**

Run: `./venv/Scripts/python -m tawla run examples/logic.twl`
Expected output:
```
1
2
3
1
```

- [ ] **Step 3: Add a README bullet** — In `README.md`, under "What the language can do", update the basics bullet or add after it:

```markdown
- **Logical operators:** `&&`, `||`, and `!` on bools, with short-circuit
  evaluation (so `u != null && u.alive()` is safe).
```

- [ ] **Step 4: Final full-suite run**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add examples/logic.twl README.md
git commit -m "Add logical-operators example and README note"
```

---

## Self-review

**Spec coverage:**
- `&&`/`||`/`!` tokens + lexing (bare `!`, no single `&`/`|`) → Task 1. ✓
- Precedence `||` < `&&` < comparison, `!` with unary → Task 2 (`logic_or`/`logic_and`, `!` in `factor`) + precedence tests. ✓
- bool operands → bool; non-bool is SemaError → Task 3. ✓
- `!` via xor; short-circuit `&&`/`||` (right evaluated only in `rhs_bb`) → Task 4 + `test_and_short_circuits`/`test_or_short_circuits` (null-deref guard proves it). ✓
- monomorphize unchanged (BinaryOp/UnaryOp already traversed) → no task needed. ✓
- Testing (truth tables, precedence, short-circuit, sema errors) → Tasks 1–4. ✓
- Example + README → Task 5. ✓

**Placeholder scan:** No TBD/TODO; every code/test step shows full content; commands have expected output.

**Type consistency:** `AND`/`OR`/`NOT` token names consistent across tokens/lexer/parser. Parser builds `BinaryOp("&&"/"||", ...)` and `UnaryOp("!", ...)` — matched by sema (`_LOGICAL`, `node.op == "!"`) and codegen (`node.op in ("&&","||")` → `_gen_logical`; `node.op == "!"` → xor). `_gen_logical` uses `i1`/`_alloca`/`cbranch`/`position_at_end` consistent with existing codegen. ✓
