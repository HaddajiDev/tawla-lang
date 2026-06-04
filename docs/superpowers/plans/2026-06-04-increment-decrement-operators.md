# Increment / Decrement Operators (`++` / `--`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add statement-only C-style `x++`, `++x`, `x--`, `--x` so loops and counters read naturally.

**Architecture:** Parse-time desugar. New `PLUS_PLUS` / `MINUS_MINUS` tokens are lexed with maximal munch; the parser rewrites the four forms into the existing `Assign(target, BinaryOp(op, target, IntLiteral(1)))` node in the two statement contexts (standalone statement and for-loop step). Sema, codegen, and monomorphize are untouched — they already handle `Assign` and `BinaryOp`.

**Tech Stack:** Python 3.11+, the Tawla compiler (`tawla/`), pytest. Tests run the CLI as a subprocess via the `run_twl` fixture (`tests/conftest.py`), which accepts bare top-level statements.

**Reference spec:** `docs/superpowers/specs/2026-06-04-increment-decrement-operators-design.md`

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `tawla/tokens.py` | Token kinds | Add `PLUS_PLUS`, `MINUS_MINUS` |
| `tawla/lexer.py` | Source → tokens | Lex `++`/`--` with maximal munch |
| `tawla/parser.py` | Tokens → AST | Desugar `++`/`--` into `Assign` in statement + for-step contexts; dispatch fix |
| `tests/test_m35.py` | Feature tests | New file (lexer unit + end-to-end + errors) |
| `examples/increment.twl` | Demo program | New file |
| `tawla_lang_docs/index.html` | Docs site | Use `i++` in for-loop; mention in operators |
| `README.md` | Project README | Use `i++`; add a bullet |
| `pyproject.toml`, `tawla/__init__.py` | Version | Bump to `1.4.0` |

Key existing signatures (do not change):
- `BinaryOp(op: str, left: Expr, right: Expr)` — arg order is **op, left, right**.
- `Assign(target: Expr, value: Expr)`.
- `IntLiteral(value: int)` — build the constant `1` as `IntLiteral(1)`.
- Valid lvalue node types: `Identifier`, `FieldAccess`, `Index` (all already imported in `parser.py`).

---

## Task 1: Lexer — `PLUS_PLUS` and `MINUS_MINUS` tokens

**Files:**
- Modify: `tawla/tokens.py` (TokenKind enum, after `MINUS = auto()` on line 39)
- Modify: `tawla/lexer.py` (two-char operator block lines 105-128; `_SINGLE` lines 10-26)
- Test: `tests/test_m35.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/test_m35.py` with:

```python
"""M35: increment/decrement operators (++ / --)."""

from tawla.lexer import tokenize
from tawla.tokens import TokenKind


def test_lexes_plusplus_and_minusminus():
    kinds = [t.kind for t in tokenize("++ -- + -")]
    assert kinds[:4] == [
        TokenKind.PLUS_PLUS,
        TokenKind.MINUS_MINUS,
        TokenKind.PLUS,
        TokenKind.MINUS,
    ]


def test_maximal_munch_no_spaces():
    # "i++" must lex as IDENT then PLUS_PLUS, not IDENT PLUS PLUS
    kinds = [t.kind for t in tokenize("i++")]
    assert kinds == [TokenKind.IDENT, TokenKind.PLUS_PLUS, TokenKind.EOF]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_m35.py -v`
Expected: FAIL with `AttributeError: PLUS_PLUS` (the enum member does not exist yet).

- [ ] **Step 3: Add the token kinds**

In `tawla/tokens.py`, insert two members right after `MINUS = auto()` (line 39):

```python
    PLUS = auto()
    MINUS = auto()
    PLUS_PLUS = auto()
    MINUS_MINUS = auto()
    STAR = auto()
```

- [ ] **Step 4: Lex them with maximal munch**

In `tawla/lexer.py`, add two branches inside the two-char operator chain. Insert them immediately after the `elif c == "|":` block (after line 121, before the `else:` on line 122):

```python
        elif c == "+":
            kind, text = (TokenKind.PLUS_PLUS, "++") if nxt == "+" else (TokenKind.PLUS, "+")
        elif c == "-":
            kind, text = (TokenKind.MINUS_MINUS, "--") if nxt == "-" else (TokenKind.MINUS, "-")
```

Then remove the now-dead `+` and `-` entries from the `_SINGLE` dict (lines 11-12), so single `+`/`-` have exactly one source of truth (the branch above). `_SINGLE` should start:

```python
_SINGLE = {
    "*": TokenKind.STAR,
    "/": TokenKind.SLASH,
    "(": TokenKind.LPAREN,
```

Note: `a--b` (no spaces) intentionally lexes as `a`, `--`, `b` and later fails to parse — same maximal-munch ambiguity as C. Write subtraction as `a - b` or `a - -b`.

- [ ] **Step 5: Run test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_m35.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add tawla/tokens.py tawla/lexer.py tests/test_m35.py
git commit -m "Lex ++ and -- tokens with maximal munch"
```

---

## Task 2: Parser — standalone increment/decrement statements

**Files:**
- Modify: `tawla/parser.py` (`statement()` dispatch line 387; `assign_or_expr_stmt` lines 413-423; add helper `_incdec_to_assign`)
- Test: `tests/test_m35.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_m35.py`:

```python
def test_postfix_increment_variable(run_twl):
    assert run_twl("int i = 0; i++; print(i);").stdout == "1\n"


def test_prefix_increment_variable(run_twl):
    assert run_twl("int i = 0; ++i; print(i);").stdout == "1\n"


def test_postfix_decrement_variable(run_twl):
    assert run_twl("int i = 5; i--; print(i);").stdout == "4\n"


def test_prefix_decrement_variable(run_twl):
    assert run_twl("int i = 5; --i; print(i);").stdout == "4\n"


def test_increment_array_element(run_twl):
    src = "int[] a = new int[3]; a[1] = 10; a[1]++; print(a[1]);"
    assert run_twl(src).stdout == "11\n"


def test_increment_float(run_twl):
    assert run_twl("float f = 1.5; f++; print(f);").stdout == "2.5\n"


def test_increment_object_field(run_twl):
    src = (
        "class Counter {"
        "    public int n;"
        "    public Counter() { this.n = 0; }"
        "    public void bump() { this.n++; }"
        "}"
        "class Main {"
        "    void main() {"
        "        Counter c = new Counter();"
        "        c.bump(); c.bump();"
        "        print(c.n);"
        "    }"
        "}"
    )
    assert run_twl(src).stdout == "2\n"


def test_longhand_still_works(run_twl):
    assert run_twl("int i = 5; i = i + 1; print(i);").stdout == "6\n"


def test_subtraction_and_unary_minus_still_lex(run_twl):
    # Guards that splitting +/- into the two-char chain didn't break single -.
    assert run_twl("int a = 10 - 3; print(a);").stdout == "7\n"
    assert run_twl("int b = 0 - 5; print(b);").stdout == "-5\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_m35.py -v`
Expected: the new end-to-end tests FAIL. `i++` currently produces a parse error (`PLUS_PLUS` is unexpected after the expression), so `run_twl(...).stdout` is `""` and `returncode` is non-zero. (`test_longhand_still_works` and `test_subtraction_and_unary_minus_still_lex` should already PASS — they guard against regressions.)

- [ ] **Step 3: Add the desugar helper**

In `tawla/parser.py`, add this method to the parser class (place it directly above `assign_or_expr_stmt`, before line 413):

```python
    def _incdec_to_assign(self, target, op_kind) -> Stmt:
        """Desugar x++ / ++x / x-- / --x into  target = target (+|-) 1."""
        if not isinstance(target, (Identifier, FieldAccess, Index)):
            raise ParseError("'++' and '--' require a variable, field, or array element")
        op = "+" if op_kind is TokenKind.PLUS_PLUS else "-"
        return Assign(target, BinaryOp(op, target, IntLiteral(1)))
```

- [ ] **Step 4: Route `++`/`--`-led statements to the assignment parser**

In `tawla/parser.py`, update the `statement()` dispatch case (line 387) to include the two new token kinds:

```python
            case (
                TokenKind.IDENT
                | TokenKind.KW_THIS
                | TokenKind.KW_NEW
                | TokenKind.PLUS_PLUS
                | TokenKind.MINUS_MINUS
            ):
                return self.assign_or_expr_stmt()
```

- [ ] **Step 5: Handle prefix and postfix in `assign_or_expr_stmt`**

Replace the body of `assign_or_expr_stmt` (lines 413-423) with:

```python
    def assign_or_expr_stmt(self) -> Stmt:
        # Prefix ++x / --x
        if self.current.kind in (TokenKind.PLUS_PLUS, TokenKind.MINUS_MINUS):
            op_kind = self.current.kind
            self.advance()
            target = self.expr()
            stmt = self._incdec_to_assign(target, op_kind)
            self.expect(TokenKind.SEMICOLON)
            return stmt

        expr = self.expr()
        if self.current.kind is TokenKind.ASSIGN:
            self.advance()
            value = self.expr()
            self.expect(TokenKind.SEMICOLON)
            if not isinstance(expr, (Identifier, FieldAccess, Index)):
                raise ParseError("invalid assignment target")
            return Assign(expr, value)
        # Postfix x++ / x--
        if self.current.kind in (TokenKind.PLUS_PLUS, TokenKind.MINUS_MINUS):
            op_kind = self.current.kind
            self.advance()
            stmt = self._incdec_to_assign(expr, op_kind)
            self.expect(TokenKind.SEMICOLON)
            return stmt
        self.expect(TokenKind.SEMICOLON)
        return ExprStmt(expr)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_m35.py -v`
Expected: PASS (all tests defined so far). The for-loop tests are added in Task 3.

- [ ] **Step 7: Commit**

```bash
git add tawla/parser.py tests/test_m35.py
git commit -m "Parse ++/-- as standalone statements (desugar to assignment)"
```

---

## Task 3: Parser — for-loop step clause

**Files:**
- Modify: `tawla/parser.py` (`_simple_step` lines 478-488)
- Test: `tests/test_m35.py`

The for-loop **init** clause already works via `assign_or_expr_stmt` (Task 2). Only the **step** clause (`_simple_step`, which has no trailing `;`) still needs handling.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_m35.py`:

```python
def test_for_loop_postfix_step(run_twl):
    src = "for (int i = 0; i < 3; i++) { print(i); }"
    assert run_twl(src).stdout == "0\n1\n2\n"


def test_for_loop_prefix_step(run_twl):
    src = "for (int i = 0; i < 3; ++i) { print(i); }"
    assert run_twl(src).stdout == "0\n1\n2\n"


def test_for_loop_decrement_step(run_twl):
    src = "for (int i = 3; i > 0; i--) { print(i); }"
    assert run_twl(src).stdout == "3\n2\n1\n"


def test_for_loop_postfix_init(run_twl):
    # init clause uses ++ too (handled by assign_or_expr_stmt)
    src = "int i = 0; for (i++; i < 3; i++) { print(i); }"
    assert run_twl(src).stdout == "1\n2\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_m35.py -k "for_loop" -v`
Expected: FAIL — the step `i++` hits a parse error (`_simple_step` parses `i`, then `++` is unexpected before `)`), so stdout is `""`.

- [ ] **Step 3: Handle prefix and postfix in `_simple_step`**

Replace the body of `_simple_step` (lines 478-488) with:

```python
    def _simple_step(self) -> Stmt:
        """The third clause of a for-loop: an assignment or expression, but with
        no trailing ';' (the ')' ends it)."""
        # Prefix ++x / --x
        if self.current.kind in (TokenKind.PLUS_PLUS, TokenKind.MINUS_MINUS):
            op_kind = self.current.kind
            self.advance()
            target = self.expr()
            return self._incdec_to_assign(target, op_kind)

        expr = self.expr()
        if self.current.kind is TokenKind.ASSIGN:
            self.advance()
            value = self.expr()
            if not isinstance(expr, (Identifier, FieldAccess, Index)):
                raise ParseError("invalid assignment target in for-loop step")
            return Assign(expr, value)
        # Postfix x++ / x--
        if self.current.kind in (TokenKind.PLUS_PLUS, TokenKind.MINUS_MINUS):
            op_kind = self.current.kind
            self.advance()
            return self._incdec_to_assign(expr, op_kind)
        return ExprStmt(expr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_m35.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add tawla/parser.py tests/test_m35.py
git commit -m "Parse ++/-- in for-loop step clause"
```

---

## Task 4: Error and edge-case behavior

**Files:**
- Test: `tests/test_m35.py` (no production code — verifies emergent behavior)

- [ ] **Step 1: Write the tests**

Append to `tests/test_m35.py`:

```python
def test_increment_non_numeric_is_sema_error(run_twl):
    # string s; s++  desugars to  s = s + 1  -> numeric-operands sema error
    r = run_twl('string s = "x"; s++; print(s);')
    assert r.returncode != 0
    assert "numeric" in r.stderr


def test_increment_in_expression_is_parse_error(run_twl):
    # statement-only: ++ cannot produce a value
    r = run_twl("int y = 0; int z = y++; print(z);")
    assert r.returncode != 0


def test_print_of_increment_is_parse_error(run_twl):
    r = run_twl("int i = 0; print(i++);")
    assert r.returncode != 0
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest tests/test_m35.py -v`
Expected: PASS. These behaviors already emerge from the design:
- `s++` → `s = s + 1` → sema rejects `string + int` with a message containing "numeric".
- `int z = y++;` → `var_decl` parses `int z =`, then `self.expr()` reads `y` and stops; the leftover `++` is not a `;`, so `expect(SEMICOLON)` raises a `ParseError`.
- `print(i++)` → after `i`, the `)` is expected but `++` appears → `ParseError`.

If `test_increment_non_numeric_is_sema_error` fails on the substring match, confirm the exact wording by running:
`venv/Scripts/python.exe -m tawla run` on a temp file containing `string s = "x"; s++;` and read stderr; the message comes from `sema.py` (`operator '+' requires numeric operands, ...`). Adjust the asserted substring to a stable word in that message if needed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_m35.py
git commit -m "Test ++/-- error cases (non-numeric target, expression position)"
```

---

## Task 5: Example, docs, README, version bump, final verification

**Files:**
- Create: `examples/increment.twl`
- Modify: `tawla_lang_docs/index.html` (control-flow section; operators section)
- Modify: `README.md` (line ~66 for-loop bullet; add increment bullet)
- Modify: `pyproject.toml` (line 3), `tawla/__init__.py` (line 3)

- [ ] **Step 1: Create the example**

Create `examples/increment.twl`:

```tawla
// Increment / decrement operators: ++ and -- are shorthand for
// "add or subtract one". They are statements (no value), and work on
// variables, object fields, and array elements.

class Main {
    void main() {
        int sum = 0;
        for (int i = 1; i <= 5; i++) {
            sum = sum + i;
        }
        print(sum);            // 15

        int n = 3;
        n--;
        --n;
        print(n);              // 1

        int[] a = new int[3];
        a[0] = 41;
        a[0]++;
        print(a[0]);           // 42
    }
}
```

- [ ] **Step 2: Verify the example runs**

Run: `venv/Scripts/python.exe -m tawla run examples/increment.twl`
Expected output:
```
15
1
42
```

- [ ] **Step 3: Update the docs control-flow section**

In `tawla_lang_docs/index.html`, in the `#control-flow` section, change the for-loop step from `i = i + 1` to `i++`. Replace:

```html
for (int i = 1; i &lt;= 10; i = i + 1) {
```

with:

```html
for (int i = 1; i &lt;= 10; i++) {
```

- [ ] **Step 4: Mention `++`/`--` in the docs operators section**

In `tawla_lang_docs/index.html`, inside the `#operators` section, add this paragraph just before the section's closing `</section>` tag:

```html
      <p>Increment and decrement: <code>i++</code>, <code>++i</code>, <code>i--</code>, and <code>--i</code> are shorthand for <code>i = i + 1</code> / <code>i = i - 1</code>. They are statements (not expressions), so they stand on their own line or drive a <code>for</code> loop's step; they work on variables, object fields, and array elements.</p>
```

- [ ] **Step 5: Update the README**

In `README.md`, change the `for` loops bullet (around line 66) from:

```markdown
- **`for` loops:** the C-style `for (int i = 0; i < n; i = i + 1) { ... }`, with
  the loop variable scoped to the loop.
```

to:

```markdown
- **`for` loops:** the C-style `for (int i = 0; i < n; i++) { ... }`, with
  the loop variable scoped to the loop.
- **Increment/decrement:** `i++`, `++i`, `i--`, `--i` as shorthand for
  `i = i + 1` / `i = i - 1` (statement form — works on variables, fields, and
  array elements).
```

- [ ] **Step 6: Bump the version to 1.4.0**

In `pyproject.toml` line 3, change `version = "1.3.0"` to `version = "1.4.0"`.
In `tawla/__init__.py` line 3, change `__version__ = "1.3.0"` to `__version__ = "1.4.0"`.

- [ ] **Step 7: Run the full test suite**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass (existing suite + the new `tests/test_m35.py`). No regressions.

- [ ] **Step 8: Verify the version**

Run: `venv/Scripts/python.exe -m tawla version`
Expected: `tawlac 1.4.0`

- [ ] **Step 9: Commit**

```bash
git add examples/increment.twl tawla_lang_docs/index.html README.md pyproject.toml tawla/__init__.py
git commit -m "Add increment example, docs, README; bump to 1.4.0"
```

Note: `tawla_lang_docs/` is a **separate git repo** (the docs site). The `index.html` edit must be committed and pushed there separately to go live:

```bash
cd D:\Projects\tawla_lang_docs
git add index.html
git commit -m "Document ++ / -- operators"
git push
```

---

## Done criteria

- `i++`, `++i`, `i--`, `--i` work as statements on variables, fields, and array elements.
- They work as a for-loop step and init clause.
- `int` and `float` targets both increment correctly.
- Non-numeric targets and expression-position uses are rejected with errors.
- Full pytest suite green; `tawlac version` reports `1.4.0`.
- Publish to PyPI is a **separate step on the user's go-ahead** (not part of this plan).
