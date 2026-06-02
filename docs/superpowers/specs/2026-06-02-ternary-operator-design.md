# Design: ternary operator (cond ? a : b)

Status: approved (brainstorm) — pending implementation
Date: 2026-06-02
Milestone: M29 — additive; bundles with logical operators into **1.2.0**

## Goal

Add the conditional expression `cond ? a : b` so a value can be chosen inline
without an `if` statement.

## Semantics

- `cond` must be `bool` (compile error otherwise).
- The two branches must have a **common type**, computed with the existing
  subtype rules:
  - equal types → that type;
  - `int` and `float` → `float`;
  - a class and one of its ancestors → the ancestor;
  - `null` and a reference type → that reference type;
  - otherwise (e.g. `int` vs `string`) → compile error
    ("incompatible branches").
  The result type is that common type.
- **Lazy:** only the taken branch is evaluated, like an `if`. So
  `x != null ? x.id() : 0` never calls a method on a null `x`.

```tawla
int max = a > b ? a : b;
string label = ok ? "yes" : "no";
int id = u != null ? u.id() : 0;
```

## Precedence and associativity

The ternary is the **lowest-precedence** operator, sitting just above the bare
expression, below `||`:

```
?:            (lowest)
||
&&
== != < <= > >=
+ -
* /
- ! x
```

- `p || q ? x : y` parses as `(p || q) ? x : y`.
- **Right-associative:** `a ? b : c ? d : e` parses as `a ? b : (c ? d : e)`.
- The then-branch is a full `expr` (so `a ? b ? c : d : e` works); the
  else-branch recurses into `ternary`.

## Pipeline changes

- **tokens.py:** add `QUESTION` (`?`). `COLON` already exists (used by
  `class X : Base`).
- **lexer.py:** map `?` → `QUESTION` in the single-character table.
- **ast_nodes.py:** add
  ```python
  @dataclass
  class Ternary(Expr):
      cond: Expr
      then_expr: Expr
      else_expr: Expr
      result_type: str | None = None   # filled in by sema
  ```
- **parser.py:** `expr()` enters at a new `ternary()`:
  ```
  expr    := ternary
  ternary := logic_or ('?' expr ':' ternary)?
  ```
  `logic_or` and below are unchanged.
- **sema.py:** in `_check_expr`, handle `Ternary`: require `cond` is `BOOL`;
  compute the common type of the two branch types via a small helper
  (`t1` if `_is_subtype(t2, t1)`, else `t2` if `_is_subtype(t1, t2)`, else
  `SemaError`); set `node.result_type = common.name`; return `common`. Reject a
  `VOID` branch.
- **codegen.py:** in `_gen_expr`, handle `Ternary` like an `if`-expression:
  allocate a result slot of `self._llvm_type(node.result_type)`; evaluate
  `cond`; `cbranch` to a then-block and an else-block; in each, generate the
  branch expression, `_coerce` it to the slot type, store, and branch to a merge
  block; at the merge, load the slot. Only the taken branch's expression is
  generated into its block, so the other isn't evaluated at runtime.
- **monomorphize.py:** in `xf_expr`, add a `Ternary` case that transforms
  `cond`/`then_expr`/`else_expr` (the `result_type` is filled later by sema, so
  it stays `None` through monomorphization).

## Testing

`tests/test_m29.py`:
- selection: `true ? 1 : 2` → 1; `false ? 1 : 2` → 2 (via `print`).
- common type: `cond ? 1 : 2.0` is float (prints `1`/`2`); class/base branches
  assign to a base-typed variable; `cond ? someObj : null` works.
- lazy: `A a = null; int id = a != null ? a.v() : 0;` runs and yields `0`
  (the method is not called) — non-zero exit / "null reference" would mean it
  was evaluated.
- nesting/right-assoc: `n == 0 ? 10 : n == 1 ? 20 : 30` returns 10/20/30 for
  n=0/1/2.
- precedence with `||`: `(true || false) ? 1 : 2` and `true || false ? 1 : 2`
  both → 1.
- sema errors: non-bool `cond` (`5 ? 1 : 2`); incompatible branches
  (`true ? 1 : "x"`).
- regression: full suite stays green.

Example: a small `examples/ternary.twl` (e.g. a `max` and a label).

## Out of scope

- A null-coalescing `?:` / `??` operator.
- Ternary as an assignment target.
