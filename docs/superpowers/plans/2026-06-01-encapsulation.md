# Encapsulation (public/protected/private) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add C#-style access modifiers (`public`/`protected`/`private`) to class members, enforced at compile time, with members defaulting to `private` (constructors to `public`).

**Architecture:** Modifiers are parsed onto `FieldDecl`/`MethodDecl`/`CtorDecl` (with defaults applied in the parser). Sema records each member's `(visibility, declaring-class)`, enforces access at field read/write, method call, and `new`, and applies the interaction rules. Codegen is untouched. Because this makes members private by default, it is a **breaking change** and includes a migration of all existing Tawla source.

**Tech Stack:** Python 3.11+, llvmlite. Compile-time checks tested by calling `tokenize`/`parse`/`check` directly; runtime behavior via the `run_twl` subprocess fixture.

**Reference spec:** `docs/superpowers/specs/2026-06-01-encapsulation-design.md`

**Milestone:** M26 — **breaking**, ships as **1.0.0** (release is a separate user-triggered step).

---

## File structure

- `tawla/tokens.py` — add `KW_PUBLIC`/`KW_PROTECTED`/`KW_PRIVATE` + keywords.
- `tawla/ast_nodes.py` — `visibility` field on `FieldDecl`, `MethodDecl`, `CtorDecl` (with defaults).
- `tawla/parser.py` — consume an optional modifier at the start of a class member; apply defaults.
- `tawla/sema.py` — track visibility/owner in `ClassInfo`; enforce access; interaction rules.
- `examples/*.twl`, `tests/test_m*.py`, `tawla/stdlib/IO.twl` — migration (add modifiers).
- `tests/test_m26.py` — new tests for visibility enforcement.
- `examples/encapsulation.twl`, `README.md` — example + note.

---

## Task 1: Parse modifiers (no enforcement yet)

**Files:**
- Modify: `tawla/tokens.py`
- Modify: `tawla/ast_nodes.py`
- Modify: `tawla/parser.py`
- Test: `tests/test_m26.py`

- [ ] **Step 1: Write the failing tests** — Create `tests/test_m26.py`:

```python
"""M26: encapsulation (public / protected / private)."""

import pytest

from tawla.ast_nodes import CtorDecl, FieldDecl, MethodDecl
from tawla.lexer import tokenize
from tawla.parser import parse


def _members(src):
    cls = parse(tokenize(src))[0]
    return cls


def test_field_defaults_private():
    cls = _members("class A { int x; }")
    assert cls.fields[0].visibility == "private"


def test_method_defaults_private():
    cls = _members("class A { int m() { return 0; } }")
    assert cls.methods[0].visibility == "private"


def test_constructor_defaults_public():
    cls = _members("class A { int x; A(int v) { this.x = v; } }")
    assert cls.ctor.visibility == "public"


def test_explicit_modifiers_parse():
    cls = _members(
        "class A { public int x; protected int y; private int z;"
        " public int m() { return 0; } private A() {} }"
    )
    vis = {f.name: f.visibility for f in cls.fields}
    assert vis == {"x": "public", "y": "protected", "z": "private"}
    assert cls.methods[0].visibility == "public"
    assert cls.ctor.visibility == "private"


def test_public_abstract_method_parses():
    cls = _members("abstract class A { public abstract int m(); }")
    assert cls.methods[0].is_abstract
    assert cls.methods[0].visibility == "public"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m26.py -q`
Expected: FAIL — `AttributeError: 'FieldDecl' object has no attribute 'visibility'`.

- [ ] **Step 3: Add the tokens** — In `tawla/tokens.py`, add to `TokenKind` (after `KW_NULL`):

```python
    KW_PUBLIC = auto()
    KW_PROTECTED = auto()
    KW_PRIVATE = auto()
```

And to `KEYWORDS`:

```python
    "public": TokenKind.KW_PUBLIC,
    "protected": TokenKind.KW_PROTECTED,
    "private": TokenKind.KW_PRIVATE,
```

- [ ] **Step 4: Add visibility fields to the AST** — In `tawla/ast_nodes.py`:

```python
@dataclass
class FieldDecl:
    var_type: str
    name: str
    visibility: str = "private"


@dataclass
class MethodDecl:
    ret_type: str
    name: str
    params: list[Param]
    body: list[Stmt]
    is_abstract: bool = False
    visibility: str = "private"


@dataclass
class CtorDecl:
    params: list[Param]
    body: list[Stmt]
    visibility: str = "public"
```

- [ ] **Step 5: Parse the modifier** — In `tawla/parser.py`:

Add a module-level constant near the top (after `_TYPE_TOKENS`):

```python
_VISIBILITY = {
    TokenKind.KW_PUBLIC: "public",
    TokenKind.KW_PROTECTED: "protected",
    TokenKind.KW_PRIVATE: "private",
}
```

In `class_decl`, at the top of the `while self.current.kind is not TokenKind.RBRACE:` loop body (right after the EOF check), consume an optional modifier and thread it through:

```python
        while self.current.kind is not TokenKind.RBRACE:
            if self.current.kind is TokenKind.EOF:
                raise ParseError(f"unexpected end of input: missing '}}' for class {name!r}")
            visibility = None
            if self.current.kind in _VISIBILITY:
                visibility = _VISIBILITY[self.advance().kind]
            if self.current.kind is TokenKind.KW_ABSTRACT:
                self.advance()
                ret_type = self.type_name()
                mname = self.expect(TokenKind.IDENT).text
                params = self.param_list()
                self.expect(TokenKind.SEMICOLON)
                methods.append(MethodDecl(
                    ret_type, mname, params, [], is_abstract=True,
                    visibility=visibility or "private",
                ))
            elif self.current.kind is TokenKind.IDENT and self.current.text == name \
                    and self.peek(1).kind is TokenKind.LPAREN:
                if ctor is not None:
                    raise ParseError(f"class {name!r} has more than one constructor")
                ctor = self.ctor_decl(visibility or "public")
            else:
                member_type = self.type_name()
                member_name = self.expect(TokenKind.IDENT).text
                if self.current.kind is TokenKind.LPAREN:
                    methods.append(self.method_decl(member_type, member_name, visibility or "private"))
                else:
                    self.expect(TokenKind.SEMICOLON)
                    fields.append(FieldDecl(member_type, member_name, visibility or "private"))
```

Update the two helpers to accept visibility:

```python
    def ctor_decl(self, visibility: str) -> CtorDecl:
        self.advance()
        params = self.param_list()
        body = self.block()
        return CtorDecl(params, body, visibility)

    def method_decl(self, ret_type: str, name: str, visibility: str) -> MethodDecl:
        params = self.param_list()
        body = self.block()
        return MethodDecl(ret_type, name, params, body, visibility=visibility)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m26.py -q`
Expected: PASS (5 passed).

- [ ] **Step 7: Run the full suite (must still be green — no enforcement yet)**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS (parsing modifiers but not enforcing; existing code unaffected).

- [ ] **Step 8: Commit**

```bash
git add tawla/tokens.py tawla/ast_nodes.py tawla/parser.py tests/test_m26.py
git commit -m "Parse public/protected/private modifiers on class members"
```

---

## Task 2: Sema — track visibility, enforce access, interaction rules, migrate

This is the breaking change. Implement enforcement, then migrate all existing source so the suite is green at commit time.

**Files:**
- Modify: `tawla/sema.py`
- Modify: `examples/*.twl`, `tawla/stdlib/IO.twl`, `tests/test_m*.py` (migration)
- Test: `tests/test_m26.py`

- [ ] **Step 1: Write the failing enforcement tests** — Append to `tests/test_m26.py`:

```python
from tawla.sema import SemaError, check


def _sema(src):
    return check(parse(tokenize(src)))


def test_public_method_callable_from_outside():
    _sema(
        "class A { public int m() { return 1; } }"
        " class Main { void main() { A a = new A(); print(a.m()); } }"
    )


def test_private_method_not_callable_from_outside():
    with pytest.raises(SemaError):
        _sema(
            "class A { private int m() { return 1; } }"
            " class Main { void main() { A a = new A(); print(a.m()); } }"
        )


def test_private_member_usable_within_same_class():
    _sema(
        "class A { private int x;"
        " public int get() { return this.x; } }"
    )


def test_protected_field_usable_in_subclass():
    _sema(
        "class A { protected int x; }"
        " class B : A { public int get() { return this.x; } }"
    )


def test_protected_field_not_usable_from_outside():
    with pytest.raises(SemaError):
        _sema(
            "class A { protected int x; }"
            " class Main { void main() { A a = new A(); print(a.x); } }"
        )


def test_private_field_not_usable_in_subclass():
    with pytest.raises(SemaError):
        _sema(
            "class A { private int x; }"
            " class B : A { public int get() { return this.x; } }"
        )


def test_private_field_not_usable_from_outside():
    with pytest.raises(SemaError):
        _sema(
            "class A { private int x; }"
            " class Main { void main() { A a = new A(); print(a.x); } }"
        )


def test_private_constructor_blocks_new_from_outside():
    with pytest.raises(SemaError):
        _sema(
            "class A { private A() {} }"
            " class Main { void main() { A a = new A(); } }"
        )


def test_public_constructor_allows_new():
    _sema(
        "class A { public A() {} }"
        " class Main { void main() { A a = new A(); } }"
    )


def test_interface_impl_must_be_public():
    with pytest.raises(SemaError):
        _sema(
            "interface Shape { int area(); }"
            " class Sq : Shape { private int area() { return 1; } }"
        )


def test_abstract_method_cannot_be_private():
    with pytest.raises(SemaError):
        _sema("abstract class A { private abstract int m(); }")


def test_override_must_keep_visibility():
    with pytest.raises(SemaError):
        _sema(
            "class A { public int m() { return 1; } }"
            " class B : A { private int m() { return 2; } }"
        )
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m26.py -q -k "private or protected or interface_impl or abstract_method_cannot or override_must or public_constructor or public_method"`
Expected: the negative tests FAIL (no SemaError raised — access not enforced yet).

- [ ] **Step 3: Track visibility in `ClassInfo`** — In `tawla/sema.py`, add to `ClassInfo.__init__`:

```python
        self.field_vis: dict[str, tuple[str, str]] = {}   # name -> (visibility, owner class)
        self.method_vis: dict[str, tuple[str, str]] = {}
        self.ctor_vis: str = "public"
```

In `_resolve_class`, when inheriting from the parent (inside the `if c.parent is not None:` block, alongside the existing `info.fields.update(...)`), copy visibility maps:

```python
            info.field_vis.update(base.field_vis)
            info.method_vis.update(base.method_vis)
```

When processing own fields (the `for fld in c.fields:` loop), record visibility:

```python
            info.fields[fld.name] = self._type_from_name(fld.var_type)
            info.field_vis[fld.name] = (fld.visibility, name)
```

When processing own methods (the `for m in c.methods:` loop), check the override-visibility rule and record:

```python
            if m.name in info.method_vis and info.method_vis[m.name][0] != m.visibility:
                raise SemaError(
                    f"override of method {m.name!r} in class {name!r} must keep "
                    f"visibility {info.method_vis[m.name][0]!r}"
                )
            info.method_vis[m.name] = (m.visibility, name)
            if m.is_abstract and m.visibility == "private":
                raise SemaError(f"abstract method {m.name!r} cannot be private")
```

Set the constructor visibility (in the `if c.ctor is not None:` block):

```python
            info.ctor_vis = c.ctor.visibility
```

- [ ] **Step 4: Add the access-check helpers** — In `tawla/sema.py`, add to the `Sema` class:

```python
    def _same_or_subclass(self, cls: str | None, owner: str) -> bool:
        name = cls
        while name is not None:
            if name == owner:
                return True
            name = self.classes[name].parent if name in self.classes else None
        return False

    def _check_access(self, visibility: str, owner: str, what: str) -> None:
        if visibility == "public":
            return
        if visibility == "private":
            if self.current_class != owner:
                raise SemaError(f"{what} is private to class {owner!r}")
        elif visibility == "protected":
            if not self._same_or_subclass(self.current_class, owner):
                raise SemaError(
                    f"{what} is protected; only {owner!r} and its subclasses may use it"
                )
```

- [ ] **Step 5: Enforce on field access** — In `_check_expr`'s `FieldAccess` branch, after the existing `if node.field not in info.fields: raise ...` line and before `return info.fields[node.field]`:

```python
            vis, owner = info.field_vis[node.field]
            self._check_access(vis, owner, f"field {node.field!r}")
            return info.fields[node.field]
```

(Field *writes* go through `_check_lvalue`, which calls `_check_expr` on the field-access node, so this covers writes too.)

- [ ] **Step 6: Enforce on method calls** — In `_check_expr`'s `MethodCall` branch, after `if node.method not in methods: raise ...` and before `params, ret = methods[node.method]`:

```python
            if obj_type.name in self.classes:
                vis, owner = self.classes[obj_type.name].method_vis[node.method]
                self._check_access(vis, owner, f"method {node.method!r}")
            params, ret = methods[node.method]
```

(Interface-typed receivers skip the check — interface methods are public.)

- [ ] **Step 7: Enforce on construction** — In `_check_expr`'s `New` branch, after the abstract-class check and before checking ctor args:

```python
            self._check_access(info.ctor_vis, node.class_name, f"constructor of {node.class_name!r}")
```

- [ ] **Step 8: Enforce interface-impl-is-public** — In `_verify_implements`, after the existing signature-match check for each interface method `mname`:

```python
                if info.method_vis[mname][0] != "public":
                    raise SemaError(
                        f"method {mname!r} implements interface {iface!r} and must be public"
                    )
```

- [ ] **Step 9: Run the M26 tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m26.py -q`
Expected: PASS (all M26 tests).

- [ ] **Step 10: Run the full suite — expect MANY failures (this is the migration to-do list)**

Run: `./venv/Scripts/python -m pytest -q`
Expected: FAIL — existing programs use members across class boundaries that are now private.

- [ ] **Step 11: Migrate the examples** — Apply this rule everywhere: a member used *outside its declaring class* needs a modifier. Add modifiers to `examples/*.twl`:
  - Method called from another class or top-level, or implementing an interface, or `abstract` → `public`.
  - Field read/written by a subclass → `protected`; field read/written from outside its class → `public`.
  - Fields/methods used only inside their own class → leave `private`.

Concretely (verify each by reading the file):
  - `point.twl`: `sum`, `scaled` → `public`.
  - `animals.twl`: `legs` → `protected`; `legCount`, `speak` (Animal + overrides in Dog/Snake) → `public`.
  - `super.twl`: `legCount`, `who` → `public` (fields stay private — used only within their own class).
  - `interfaces.twl`: `area`, `sides` → `public`.
  - `shapes.twl`: the interface-implementing/area methods → `public`.
  - `abstract.twl`: abstract methods and their overrides → `public`; any subclass-accessed field → `protected`.
  - `generics.twl`: `get`, `set`, `getFirst`, `getSecond` → `public` (fields stay private).
  - `floats.twl`: `area` → `public`.
  - `strings.twl`, `arrays.twl`, `gc.twl`: methods called externally → `public`.
  - `nullable.twl`: `Account.balance` (read as `a.balance` from `Main`) → `public`.
  - `imports/geometry.twl`: `Point.sum` → `public` (`area` is a free function).

- [ ] **Step 12: Migrate the test programs** — Re-run the suite and fix each failing embedded `.twl` source string in `tests/test_m*.py` by the same rule (methods called cross-class → `public`, subclass-accessed fields → `protected`, externally-read fields → `public`). Also update `tawla/stdlib/IO.twl` only if a failure points to it (its functions are free functions, so likely no change). Iterate:

Run: `./venv/Scripts/python -m pytest -q`
Repeat fixing until: PASS (all tests green).

- [ ] **Step 13: Commit**

```bash
git add -A
git commit -m "Enforce public/protected/private access and migrate existing code"
```

---

## Task 3: Example, README note, final verification

**Files:**
- Create: `examples/encapsulation.twl`
- Modify: `README.md`

- [ ] **Step 1: Write the example** — Create `examples/encapsulation.twl`:

```tawla
// Access control: members are private by default. Use public/protected to widen.

class Counter {
    private int count;          // hidden from the outside

    public Counter() { this.count = 0; }
    public void bump() { this.count = this.count + 1; }
    public int value() { return this.count; }
}

class Main {
    void main() {
        Counter c = new Counter();
        c.bump();
        c.bump();
        print(c.value());       // 2
        // c.count here would be a compile error: count is private
    }
}
```

- [ ] **Step 2: Run the example**

Run: `./venv/Scripts/python -m tawla run examples/encapsulation.twl`
Expected output: `2`

- [ ] **Step 3: Add a README bullet** — In `README.md`, under "What the language can do", after the inheritance bullet:

```markdown
- **Encapsulation:** members are `private` by default; mark them `public` to
  expose them or `protected` to share with subclasses. Constructors are `public`
  by default. Access is checked at compile time. (Note: code written for Tawla
  0.x needs `public` added to anything used across class boundaries.)
```

- [ ] **Step 4: Final full-suite run**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add examples/encapsulation.twl README.md
git commit -m "Add encapsulation example and README note"
```

---

## Self-review

**Spec coverage:**
- Three modifiers + keywords → Task 1. ✓
- Defaults (field/method private, ctor public) → Task 1 (parser defaults) + tests. ✓
- Access checked at field read/write, method call, `new` → Task 2 Steps 5–7. ✓
- `protected` = class + subclasses; `private` = class only → `_check_access` + `_same_or_subclass` (Task 2 Step 4). ✓
- Inheritance copies member visibility/owner → Task 2 Step 3. ✓
- Interface impls must be public → Task 2 Step 8. ✓
- Abstract methods can't be private → Task 2 Step 3. ✓
- Override keeps base visibility → Task 2 Step 3. ✓
- Interface signatures take no modifier → not parsed for interfaces (interface_decl untouched); their methods are looked up from the interface table (always public, never access-checked). ✓
- Codegen unchanged → no codegen task. ✓
- Migration of examples/tests/stdlib + README note → Task 2 Steps 11–12, Task 3 Step 3. ✓
- Testing (enforcement matrix, ctor, interface/abstract/override, regression, smoke) → Task 1 + Task 2 tests + Task 3 example. ✓

**Placeholder scan:** No TBD/TODO. Migration steps give an exact rule + per-file modifier list + a failure-driven loop with the exact command; this is concrete (the set of edits is mechanical and compiler-verified) rather than a placeholder.

**Type consistency:** `visibility` field names match across AST/parser/sema. `field_vis`/`method_vis` are `dict[name -> (visibility, owner)]`; `ctor_vis` is a string — used consistently in Steps 3–8. `_check_access(visibility, owner, what)` and `_same_or_subclass(cls, owner)` signatures match their call sites. `current_class` is the existing sema attribute. ✓
