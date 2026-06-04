# Increment / Decrement Operators (`++` / `--`) — Design

## Goal

Add C-style increment and decrement operators — `x++`, `++x`, `x--`, `--x` — to
Tawla, primarily so for-loops and counters read naturally
(`for (int i = 0; i < n; i++)`).

## Semantics

**Statement-only.** Increment/decrement are statements, not value-producing
expressions. This is consistent with assignment, which in Tawla is also a
statement (`x = ...;` cannot appear inside another expression).

- `x++`, `++x`  mean exactly  `x = x + 1;`
- `x--`, `--x`  mean exactly  `x = x - 1;`

Because no value is produced, the prefix and postfix forms are **accepted and
behave identically** — there is no observable pre/post distinction in statement
position. Both forms exist only so the syntax feels familiar.

**Where they are valid** — anywhere an assignment is valid:

- as a standalone statement:  `i++;`
- as the third clause of a for-loop:  `for (int i = 0; i < n; i++) { ... }`

**Where they are NOT valid** — inside an expression. `int y = x++;`,
`arr[i++]`, `print(x++)` are all parse errors. This mirrors the existing rule
that assignment is not an expression.

## Targets

Any assignable lvalue — the same set `Assign` already supports:

| Target          | Example          | Desugars to                          |
|-----------------|------------------|--------------------------------------|
| local variable  | `i++`            | `i = i + 1`                          |
| object field    | `this.count++`   | `this.count = this.count + 1`        |
| array element   | `arr[i]++`       | `arr[i] = arr[i] + 1`                |

## Types

`int` and `float`. The desugared `x + 1` relies on existing sema arithmetic
rules: `float + int` widens to `float` (sema returns `FLOAT if FLOAT in
(left, right) else INT`), so a `float` target increments correctly with the
integer literal `1`.

A non-numeric target (`string`, `bool`, object, array) produces a normal sema
error from the desugared `BinaryOp` — "operator '+' requires numeric operands,
got <type> and int". This is the desired behavior; no extra checking needed.

## Implementation — Approach A: parse-time desugar

The parser rewrites the four forms into the existing
`Assign(target, BinaryOp(target, op, IntLiteral(1)))` node. Nothing downstream
changes — sema, codegen, monomorphize, and the for-loop step all already handle
`Assign` and `BinaryOp`.

### `tokens.py`

Add two token kinds: `PLUS_PLUS` (`++`) and `MINUS_MINUS` (`--`).

### `lexer.py`

Lex `++` and `--` with **maximal munch**: when the scanner sees `+`, peek the
next character — if it is also `+`, emit `PLUS_PLUS` and consume both; otherwise
emit the existing single `PLUS`. Same logic for `-` → `MINUS_MINUS` / `MINUS`.
This must run before the single-character `+`/`-` cases.

Note on ambiguity (acceptable, matches C): `a--b` lexes as `a`, `--`, `b` and
then fails to parse, exactly as in C. Code that means subtraction writes
`a - -b` or `a - b`.

### `parser.py`

Increment/decrement are handled **only** in the two statement-producing
contexts, never in the expression grammar:

1. `assign_or_expr_stmt` (standalone statement, consumes trailing `;`)
2. `_simple_step` (for-loop third clause, no trailing `;`)

A shared helper builds the desugared node:

```python
def _incdec_to_assign(self, target, op_token) -> Assign:
    if not isinstance(target, (Identifier, FieldAccess, Index)):
        raise ParseError("'++'/'--' requires a variable, field, or array element")
    op = "+" if op_token is TokenKind.PLUS_PLUS else "-"
    return Assign(target, BinaryOp(target, op, IntLiteral(1)))
```

In each context:

- **Prefix** (`++x`): detected at the start — if the first token is
  `PLUS_PLUS`/`MINUS_MINUS`, remember the op, advance, parse the lvalue with
  `self.expr()`, then build the Assign.
- **Postfix** (`x++`): after parsing the leading `self.expr()`, if the current
  token is `PLUS_PLUS`/`MINUS_MINUS`, advance and build the Assign. (Checked
  alongside the existing `ASSIGN` branch.)

`statement()` dispatch already falls through to `assign_or_expr_stmt` for input
that is not a keyword/declaration, so a statement beginning with `++`/`--`
routes there with no dispatch change. The integer-literal node is `IntLiteral`,
constructed as `IntLiteral(1)` (confirmed in `ast_nodes.py` / `parser.py`).

### `sema.py`, `codegen.py`, `monomorphize.py`

No changes. The desugared `Assign` / `BinaryOp` use existing code paths.

## Testing — `tests/test_m35.py`

- `int` postfix `i++` and prefix `++i` each increment by 1
- `int` postfix `i--` and prefix `--i` each decrement by 1
- object field: `this.count++` updates the field
- array element: `arr[i]++` updates the element at `i`
- `float` target: `f++` increments a float (prints `1` higher)
- inside a for-loop step: `for (int i = 0; i < 3; i++)` runs 3 times
- prefix in a for-loop step: `for (...; ; ++i)` works the same
- longhand `i = i + 1` still works (regression guard)
- sema error: `string s = "x"; s++;` rejected with a numeric-operands error
- parse error: `int y = x++;` rejected (statement-only)

## Wrap-up

- Add an example `.twl` demonstrating `++`/`--` in a counting loop.
- Docs (`tawla_lang_docs/index.html`): show `i++` in the control-flow / for-loop
  section and mention `++`/`--` in operators.
- README note under the language tour.
- Version bump to **1.4.0** (additive language feature).
- Publish to PyPI on the user's go-ahead.
