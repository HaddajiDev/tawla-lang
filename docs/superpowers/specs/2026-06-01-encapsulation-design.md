# Design: encapsulation (public / protected / private)

Status: approved (brainstorm) — pending implementation
Date: 2026-06-01
Milestone: M26 — **breaking**, ships as **1.0.0**

## Goal

Give Tawla C#-style access control on class members so implementation details can
be hidden. Three modifiers — `public`, `protected`, `private` — enforced entirely
at compile time (sema). No runtime/codegen change.

This is a **breaking change**: members default to `private`, so existing programs
that call methods or read fields across class boundaries must add modifiers. A
migration pass updates the examples, tests, and scaffold as part of this work.

## The model

### Modifiers and what they grant

- `public` — accessible from anywhere.
- `protected` — accessible from the declaring class and any subclass of it.
- `private` — accessible only from the declaring class.

### Defaults (no modifier written)

- fields → `private`
- methods → `private`
- constructors → `public`

Constructors default to `public` (unlike C#'s explicit-ctor-is-private rule) so
that `new X(...)` keeps working everywhere; the niche private/factory pattern is
still available by writing `private X(...)`.

```tawla
class Animal {
    protected int legs;             // subclasses may use it
    private int secret;             // Animal only
    public int legCount() { return this.legs; }
    Animal(int n) { this.legs = n; }   // public by default
}

class Dog : Animal {
    Dog() { this.legs = 4; }        // ok: legs is protected
    // this.secret here -> compile error
}
```

### Where access is checked

The "current class" is the class whose method/constructor body is being checked
(`None` for top-level statements and free functions — those can only touch
`public` members). Access is enforced at:

- field read — `obj.f`
- field write — `obj.f = ...`
- method call — `obj.m(...)`
- construction — `new X(...)` (the constructor's visibility)

`protected` access is allowed when the current class is the declaring class or a
subclass of it (walk the parent chain). `private` access is allowed only when the
current class *is* the declaring class.

### Interaction rules

1. **Interface implementations must be `public`.** A class method that implements
   an interface method must be declared `public`; otherwise a compile error.
2. **Abstract methods cannot be `private`** (they could never be overridden) —
   they must be `public` or `protected`.
3. **Overrides keep the base's visibility.** A subclass override must declare the
   same visibility as the method it overrides; mismatch is a compile error.
4. **Interface method signatures take no modifier** — implicitly public.

## Implementation

- **tokens.py:** add `KW_PUBLIC`, `KW_PROTECTED`, `KW_PRIVATE` (`"public"`,
  `"protected"`, `"private"`).
- **ast_nodes.py:** add a `visibility: str` field to `FieldDecl`, `MethodDecl`,
  and `CtorDecl` (values `"public"`, `"protected"`, `"private"`).
- **parser.py:** in the class-member loop, consume an optional visibility keyword
  first (before the existing `abstract` handling), then parse the member as
  today. Apply the default if none was written: `private` for fields/methods,
  `public` for constructors. `abstract` may follow a modifier
  (`public abstract int area();`).
- **sema.py:**
  - In `ClassInfo`, record each member's visibility and declaring class — e.g.
    `field_access: dict[str, tuple[str, str]]` and
    `method_access: dict[str, tuple[str, str]]` mapping name → (visibility,
    owner-class), plus a `ctor_visibility: str`. Populate during
    `_resolve_class`; inherited members copy the parent's entries (preserving the
    original owner so `protected` checks use the class that actually declared the
    member). On override, verify the new visibility equals the inherited one.
  - Add a helper `_check_access(visibility, owner, what)` that raises `SemaError`
    unless: `public`; or `private` and `current_class == owner`; or `protected`
    and `current_class` is `owner` or a subclass of `owner`.
  - Add a helper to test "is class A the same as or a subclass of class B" by
    walking A's parent chain.
  - Call `_check_access` at: `FieldAccess` (in `_check_expr`), field-target in
    `_check_lvalue`, `MethodCall` (in `_check_expr`), and `New` (constructor).
  - During `_verify_implements`, require the implementing method's visibility to
    be `public`.
  - During `_resolve_class`, require abstract methods to be non-`private`.
- **codegen.py:** no change.

## Migration (part of this milestone)

Update existing Tawla source so it compiles under private-by-default:

- examples (`examples/*.twl`) and bundled stdlib are reviewed; methods called
  across class boundaries get `public`, subclass-shared fields get `protected`,
  interface/abstract methods get `public`.
- test programs in `tests/test_m*.py` (embedded `.twl` source strings) get the
  same treatment so the suite passes.
- `Main.main()` and constructors need no change. Free functions (incl. `IO.twl`)
  are unaffected.
- scaffold template (`tawla/project.py`) — keep it minimal; `main()` stays as-is
  (runtime-invoked). Add a short README note that 0.x code needs `public` added.

## Testing

New `tests/test_m26.py` — call `check(parse(tokenize(src)))` for compile-time
checks (no run needed):

- public method callable from outside; private method NOT callable from outside
  (SemaError); private accessible within same class (ok).
- protected field: accessible in declaring class and subclass (ok), NOT from
  outside (SemaError).
- private field: accessible in declaring class (ok), NOT in subclass (SemaError),
  NOT outside (SemaError).
- default (no modifier) field/method is private; default constructor is public.
- `private` constructor → `new X()` from outside is a SemaError; from a static
  factory method on the same class is ok.
- interface implementation declared non-public → SemaError.
- abstract method declared `private` → SemaError.
- override with a different visibility than the base → SemaError.
- regression: full suite passes after the migration.

Plus a `run_twl` smoke test that a small program using `public`/`protected`
correctly still compiles and runs end to end.

## Out of scope

- `internal`/package-level or assembly visibility.
- Visibility on free (top-level) functions — they stay globally callable.
- Property/getter-setter syntax (you still write explicit accessor methods).
