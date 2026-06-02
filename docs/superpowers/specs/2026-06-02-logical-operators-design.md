# Design: logical operators (&&, ||, !)

Status: approved (brainstorm) — pending implementation
Date: 2026-06-02
Milestone: M28 — additive, ships as **1.2.0**

## Goal

Add the boolean operators `&&` (and), `||` (or), and `!` (not), with C-style
precedence and short-circuit evaluation. This unblocks readable routing and
validation conditions (`method == "GET" && path == "/users"`,
`u != null && u.active()`) needed by the upcoming HTTP work, and is generally
useful everywhere.

## Semantics

- `&&`, `||`: both operands must be `bool`; result is `bool`.
- `!`: operand must be `bool`; result is `bool`.
- **Short-circuit:** `a && b` does not evaluate `b` when `a` is `false`;
  `a || b` does not evaluate `b` when `a` is `true`. So a guard like
  `u != null && u.active()` will not call a method on a null receiver.
- Non-`bool` operands are a compile-time `SemaError`.

## Precedence and associativity

C-style, loosest to tightest:

```
||            (loosest)
&&
== != < <= > >=     (existing comparisons)
+ -
* /
- ! x         (unary minus and not — tightest)
primary
```

So:
- `m == "GET" && p == "/users"` → `(m == "GET") && (p == "/users")`
- `a || b && c` → `a || (b && c)`
- `!found` → unary; `!a == b` → `(!a) == b` (write `!(a == b)` if you mean the other)

`&&` and `||` are left-associative. Parentheses override as usual.

## Pipeline changes

- **tokens.py:** add `AND` (`&&`), `OR` (`||`), `NOT` (`!`).
- **lexer.py:** recognize `&&` and `||` (two-char). For `!`: currently `!`
  only forms `!=`; when the next char is not `=`, emit `NOT` instead of raising
  "unexpected character '!'".
- **parser.py:** insert two precedence levels above `comparison`:
  ```
  expr       := logic_or
  logic_or   := logic_and ('||' logic_and)*
  logic_and  := comparison ('&&' comparison)*
  ```
  `expr()` now calls `logic_or()`. Add `!` to `factor`:
  `factor := ('-' | '!') factor | postfix`. `&&`/`||` build left-associative
  `BinaryOp` nodes; `!` builds a `UnaryOp("!", operand)`.
- **sema.py:** in `BinaryOp`, `&&`/`||` require both operands `BOOL` → `BOOL`
  (a new `_LOGICAL = {"&&", "||"}` set, checked before the numeric paths). In
  `UnaryOp`, `!` requires `BOOL` → `BOOL` (the existing `-` path stays
  int/float).
- **codegen.py:**
  - `UnaryOp` `"!"`: `xor` the i1 with `1` (`builder.xor(v, ir.Constant(i1, 1))`).
  - `BinaryOp` `&&`/`||`: short-circuit with blocks and a result slot, e.g. for
    `&&`: eval left; `cbranch` to a "rhs" block (eval right, store) or a "false"
    block (store `false`); merge and load. For `||`: branch to "true" (store
    `true`) or "rhs". The right operand is generated only inside the rhs block,
    so it is not evaluated when short-circuited.
- **monomorphize.py:** no change — `BinaryOp`/`UnaryOp` are already traversed
  (operator string carried through `replace`).

## Testing

`tests/test_m28.py`:
- truth tables: `true && true`, `true && false`, `false && true`, `false &&
  false`; same for `||`; `!true`, `!false` (via `print` of the bool / `if`).
- precedence: `if (1 == 1 && 2 == 2)` true; `if (1 == 2 || 3 == 3)` true;
  `a || b && c` grouping.
- short-circuit: `false && <crashing rhs>` and `true || <crashing rhs>` run
  without triggering the rhs — e.g. guard a null deref:
  `User u = null; if (u != null && u.active()) { ... }` runs and takes the else
  (the method is never called on null).
- `!` in a condition: `if (!found) { ... }`.
- sema errors: `1 && 2` (non-bool), `!5` (non-bool).
- regression: full suite stays green.

Example: extend an example (or a small new one) using `&&`/`||`/`!` in an `if`.

## Out of scope

- Bitwise operators (`&`, `|`, `^`).
- Logical operators on non-bool (no "truthiness").
