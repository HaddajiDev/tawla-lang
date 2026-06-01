# Design: `null` and default-initialized variables

Status: approved (brainstorm) — pending implementation
Date: 2026-06-01
Milestone: M25 (ships as **0.4.0**, additive / non-breaking)

## Goal

Give Tawla a real `null` so reference values can be "absent", and allow
declarations without an initializer (defaulting to the type's zero value). This
is the foundation for collections (`Map.get` returning `null` for a missing
reference value) and general backend code.

This is scoped to **`null` + clear runtime errors**. It explicitly does NOT
include static null-safety (no `User?` vs `User`, no compiler-enforced
null-checking before use). Misuse is caught at runtime, not compile time.

## Semantics

### The `null` literal

`null` is a new keyword and expression. It denotes "no object".

It is assignable **only to reference types**:
- class types, interface types, `string`, array types (`T[]`), and (later)
  the collection classes `List<T>` / `Map<K,V>` (which are just classes).

It is **not** valid for value types — `int`, `float`, `bool`:

```tawla
User u = null;        // ok
string s = null;      // ok
int[] a = null;       // ok
int n = null;         // ERROR: int can't be null
var z = null;         // ERROR: can't infer a type from null
```

### Comparisons

`==` and `!=` work between a reference value and `null` (either order), and
between two nulls:

```tawla
if (u == null) { ... }
if (s != null) { print(s); }
```

Comparing a value type to `null` (`n == null`) is a compile error.

### Default-initialized declarations

Initializers become **optional for typed declarations**. A declaration with no
initializer gets the type's default:

| type            | default |
|-----------------|---------|
| `int`           | `0`     |
| `float`/`double`| `0.0`   |
| `bool`          | `false` |
| `string`        | `null`  |
| array `T[]`     | `null`  |
| class/interface | `null`  |

```tawla
int x;        // 0
bool b;       // false
User u;       // null
```

`var` with no initializer remains an **error** (nothing to infer from). This
matches the existing zero-initialization of object fields and array slots —
`null` simply names the reference-typed case.

## Runtime behavior (no static null-safety)

Because there is no compile-time null checking, every operation that
*dereferences* a reference inserts a runtime null check. If the reference is
`null`, the program prints `null reference` and exits with status 1 — the **same
mechanism already used for array out-of-bounds** (compare → branch to an error
block → `printf` the message → `exit(1)`). No new native code is required.

Checked operations:
- method call on an object or interface — `u.greet()`
- field access — `u.name`
- array indexing — `a[i]` when `a` is null
- `.length` — on a null array or null string
- `print(s)` when `s` is a null string (printf `%s` on null would crash)

A plain `u == null` test does **not** trip the check (it's a comparison, not a
dereference).

## Implementation sketch

Pipeline touch-points:

- **tokens.py:** add `KW_NULL` (`"null"`).
- **ast_nodes.py:** add `NullLiteral(Expr)`. `VarDecl.init` becomes
  `Expr | None`.
- **lexer.py:** no change (`null` is an identifier-shaped keyword).
- **parser.py:**
  - `primary`: `null` → `NullLiteral`.
  - `var_decl` / top-level var: initializer optional for **typed** decls
    (`type IDENT ('=' expr)? ';'`); `var` still requires `= expr`.
- **sema.py:**
  - add `NULL = Type("null")`.
  - `NullLiteral` → `NULL`.
  - `_is_subtype(NULL, T)` is true when `T` is a reference type (class,
    interface, `string`, array, collection class); false for `int`/`float`/
    `bool`/`void`. This makes assignment, args, return, and `==`/`!=` work for
    free via existing subtype checks.
  - `VarDecl` with `init is None`: resolve declared type from `var_type`
    (error if `var`), add to scope, no subtype check.
  - keep `print` accepting `int`/`float`/`bool`/`string` (a null *string* is
    still statically `string`; the null check is a runtime concern).
- **codegen.py:**
  - a dedicated null sentinel type so a generated `null` is unambiguous (it must
    not be confused with a `string`, which is also `i8*`): an opaque
    `$null` identified struct, with `NullLiteral` → `Constant($null*, None)`.
  - `_coerce` recognizes the sentinel: to a pointer target → `Constant(target,
    None)`; to an interface struct target → zero-initialized fat pointer.
  - `VarDecl` with no init → `alloca` + store `_zero(slot_ty)`; extend the
    zero/default helper to produce a zero-initialized fat pointer for interface
    types. Reference slots still register as GC roots.
  - `==`/`!=` with a null operand: coerce the sentinel to the other operand's
    representation, then pointer compare (for interface values, compare the
    extracted object word).
  - `_null_check(ptr)`: emit compare-against-null → error block (`printf
    "null reference\n"`, `exit(1)`) / continue block. Call it before the
    dereference in method call, field access, indexing, `.length`, and the
    string branch of `print`.
- **monomorphize.py:** `xf_stmt` for `VarDecl` must keep `init = None` when
  there is no initializer (don't call `xf_expr(None)`). `NullLiteral` is a leaf
  and passes through unchanged.

## Testing

New `tests/test_m25.py`:
- assign/compare: `User u = null; if (u == null) print(1);`
- default values for each type (`int x; print(x);` → 0, `bool`, `float`).
- `string s = null;` then `s == null`.
- reference array defaults to null; object field defaults to null.
- sema errors: `int n = null;`, `var z = null;`, `int x; x == null` (value vs
  null), `var z;` (no init).
- runtime null errors (subprocess, expect non-zero exit + "null reference"):
  method call, field access, indexing, `.length`, and `print` of a null string.
- regression: `var` with initializer and all existing init forms still work.

Example: `examples/nullable.twl` showing `null`, a null check, and a
default-initialized declaration.

## Out of scope (future)

- Static null-safety (nullable vs non-null types, flow analysis).
- `null` for value types / `Nullable<int>`-style wrappers.
- These don't block collections; `Map<string,int>.get` on a missing key returns
  the zero value and is paired with `has(key)`, while `Map<string,User>.get`
  returns `null`.
