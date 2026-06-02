# Collections (List / Map) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bundled `Collections.twl` standard-library module with `List<T>` and `Map<K,V>`, plus a `panic(string)` builtin and a parser fix that lets generic-typed locals (`List<int> xs`) be declared.

**Architecture:** `List`/`Map` are ordinary generic Tawla classes (backed by arrays) shipped in `tawla/stdlib/`, so they ride on existing monomorphization + arrays + default-init with no collection-specific compiler code. Two small compiler additions support them: a `panic` builtin (sema + codegen, reusing the abort machinery) and a `_is_decl_start` extension that scans a balanced `<...>` to recognize generic-typed local declarations.

**Tech Stack:** Python 3.11+, llvmlite. Tawla programs tested via the `run_twl` subprocess fixture (it writes one entry file; `import "Collections.twl"` resolves from the bundled stdlib).

**Reference spec:** `docs/superpowers/specs/2026-06-01-collections-design.md`

**Milestone:** M27 — additive, ships as **1.1.0** (release is a separate user-triggered step).

---

## File structure

- `tawla/sema.py` — add `panic` to `_BUILTINS`.
- `tawla/codegen.py` — handle `panic` in `_gen_builtin`.
- `tawla/parser.py` — extend `_is_decl_start` for generic-typed locals.
- `tawla/stdlib/Collections.twl` — new: `List<T>` and `Map<K,V>` (ships via existing `package-data`).
- `tests/test_m27.py` — new tests.
- `examples/collections.twl`, `README.md` — example + note.

---

## Task 1: `panic(string)` builtin

**Files:**
- Modify: `tawla/sema.py`
- Modify: `tawla/codegen.py`
- Test: `tests/test_m27.py`

- [ ] **Step 1: Write the failing tests** — Create `tests/test_m27.py`:

```python
"""M27: collections (List / Map) and the panic builtin."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError


def _err(result):
    return result.stdout + result.stderr


def test_panic_aborts(run_twl):
    src = 'class Main { void main() { print(1); panic("boom"); print(2); } }'
    r = run_twl(src)
    assert r.returncode != 0
    assert "boom" in _err(r)
    assert "1\n" in r.stdout       # ran before the panic
    assert "2" not in r.stdout     # never reached


def test_panic_wrong_arg_type_is_error():
    with pytest.raises(SemaError):
        run_source("panic(5);")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m27.py -q`
Expected: FAIL — `test_panic_aborts` exits 0 / "undefined function 'panic'".

- [ ] **Step 3: Register the builtin in sema** — In `tawla/sema.py`, add to the `_BUILTINS` dict:

```python
    "__io_write": ([STRING], VOID),
    "panic": ([STRING], VOID),
}
```

(Add the `panic` line inside the existing `_BUILTINS` dict; the `__io_write` line is shown for placement context.)

- [ ] **Step 4: Emit it in codegen** — In `tawla/codegen.py`, in `_gen_builtin`, add a branch (next to the other builtins, before the final `raise CodeGenError`):

```python
        if name == "panic":
            msg = self._gen_expr(args[0])
            self.builder.call(self.printf, [self._str_ptr(self._fmt_str), msg])
            return self.builder.call(self.exit, [ir.Constant(i32, 1)])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m27.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tawla/sema.py tawla/codegen.py tests/test_m27.py
git commit -m "Add panic(string) builtin"
```

---

## Task 2: Parse generic-typed local declarations

**Files:**
- Modify: `tawla/parser.py`
- Test: `tests/test_m27.py`

- [ ] **Step 1: Write the failing tests** — Append to `tests/test_m27.py`:

```python
from tawla.ast_nodes import Assign, BinaryOp, ExprStmt, VarDecl
from tawla.lexer import tokenize
from tawla.parser import parse


def test_generic_typed_local_declaration_parses():
    items = parse(tokenize("Box<int> b = makeBox();"))
    assert isinstance(items[0], VarDecl)
    assert items[0].var_type == "Box<int>"
    assert items[0].name == "b"


def test_comparison_statement_still_parses():
    # `a < b;` must remain an expression statement, not a declaration.
    items = parse(tokenize("a < b;"))
    assert isinstance(items[0], ExprStmt)
    assert isinstance(items[0].expr, BinaryOp)
```

(`makeBox()` need not exist — these tests only parse, they don't type-check.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m27.py -q -k generic_typed_local`
Expected: FAIL — `ParseError` (a generic-typed local isn't recognized as a declaration).

- [ ] **Step 3: Extend `_is_decl_start`** — In `tawla/parser.py`, replace `_is_decl_start`:

```python
    def _is_decl_start(self) -> bool:
        """True when the upcoming tokens begin a declaration (not a statement).

        `int x`, `var x`, `ClassName x`, `ClassName[] x`, or `Generic<...> x`. A
        bare IDENT followed by `=`, `.`, `(`, or `[expr]` is a statement.
        """
        k = self.current.kind
        if k in _TYPE_TOKENS or k is TokenKind.KW_VAR:
            return True
        if k is TokenKind.IDENT:
            if self.peek(1).kind is TokenKind.IDENT:
                return True
            if self.peek(1).kind is TokenKind.LBRACKET and self.peek(2).kind is TokenKind.RBRACKET:
                return True
            if self.peek(1).kind is TokenKind.LT:
                return self._generic_decl_ahead()
        return False

    def _generic_decl_ahead(self) -> bool:
        """With current=IDENT and peek(1)=`<`, scan a balanced `<...>`; it's a
        declaration if an IDENT follows the matching `>`. Bails (returns False)
        at `;`/`{`/`}`/EOF so a comparison like `a < b;` stays a statement."""
        depth = 0
        i = 1
        while True:
            kind = self.peek(i).kind
            if kind is TokenKind.LT:
                depth += 1
            elif kind is TokenKind.GT:
                depth -= 1
                if depth == 0:
                    return self.peek(i + 1).kind is TokenKind.IDENT
            elif kind in (TokenKind.EOF, TokenKind.SEMICOLON, TokenKind.LBRACE, TokenKind.RBRACE):
                return False
            i += 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m27.py -q -k "generic_typed_local or comparison_statement"`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS (existing comparison/loop tests unaffected).

- [ ] **Step 6: Commit**

```bash
git add tawla/parser.py tests/test_m27.py
git commit -m "Parse generic-typed local declarations (List<int> x)"
```

---

## Task 3: `Collections.twl` — List<T> and Map<K,V>

**Files:**
- Create: `tawla/stdlib/Collections.twl`
- Test: `tests/test_m27.py`

- [ ] **Step 1: Write the failing tests** — Append to `tests/test_m27.py`:

```python
LIST_HEADER = 'import "Collections.twl"; class Main { void main() { '
FOOTER = ' } }'


def test_list_basic(run_twl):
    src = LIST_HEADER + (
        "List<int> xs = new List<int>();"
        " xs.add(10); xs.add(20); xs.add(30);"
        " print(xs.size()); print(xs.get(0)); print(xs.get(2));"
    ) + FOOTER
    assert run_twl(src).stdout == "3\n10\n30\n"


def test_list_set(run_twl):
    src = LIST_HEADER + (
        "List<int> xs = new List<int>(); xs.add(1); xs.set(0, 99); print(xs.get(0));"
    ) + FOOTER
    assert run_twl(src).stdout == "99\n"


def test_list_grows_past_initial_capacity(run_twl):
    src = LIST_HEADER + (
        "List<int> xs = new List<int>();"
        " int i = 0; for (int j = 0; j < 10; j = j + 1) { xs.add(j * j); }"
        " print(xs.size()); print(xs.get(9));"
    ) + FOOTER
    assert run_twl(src).stdout == "10\n81\n"


def test_list_out_of_range_panics(run_twl):
    src = LIST_HEADER + "List<int> xs = new List<int>(); xs.add(1); print(xs.get(5));" + FOOTER
    r = run_twl(src)
    assert r.returncode != 0
    assert "out of range" in _err(r)


def test_map_basic(run_twl):
    src = LIST_HEADER + (
        'Map<string, int> m = new Map<string, int>();'
        ' m.put("ada", 36); m.put("bob", 7);'
        ' print(m.size()); print(m.get("ada")); print(m.get("bob"));'
    ) + FOOTER
    assert run_twl(src).stdout == "2\n36\n7\n"


def test_map_overwrite(run_twl):
    src = LIST_HEADER + (
        'Map<string, int> m = new Map<string, int>();'
        ' m.put("x", 1); m.put("x", 2); print(m.size()); print(m.get("x"));'
    ) + FOOTER
    assert run_twl(src).stdout == "1\n2\n"


def test_map_has(run_twl):
    src = LIST_HEADER + (
        'Map<string, int> m = new Map<string, int>(); m.put("x", 1);'
        ' if (m.has("x")) { print(1); } if (m.has("y")) { print(2); } else { print(3); }'
    ) + FOOTER
    assert run_twl(src).stdout == "1\n3\n"


def test_map_missing_value_type_is_zero(run_twl):
    src = LIST_HEADER + (
        'Map<string, int> m = new Map<string, int>(); print(m.get("nope"));'
    ) + FOOTER
    assert run_twl(src).stdout == "0\n"


def test_map_missing_reference_type_is_null(run_twl):
    src = (
        'import "Collections.twl";'
        ' class User { public int id; }'
        ' class Main { void main() {'
        ' Map<string, User> m = new Map<string, User>();'
        ' User u = m.get("nope"); if (u == null) { print(1); } } }'
    )
    assert run_twl(src).stdout == "1\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m27.py -q -k "list or map"`
Expected: FAIL — `LoadError: cannot find imported file 'Collections.twl'`.

- [ ] **Step 3: Create the stdlib module** — Create `tawla/stdlib/Collections.twl`:

```tawla
// Tawla's collections. Import with:  import "Collections.twl";
//
// List<T> is a growable array; Map<K,V> is parallel key/value arrays with a
// linear scan. Internals are private; the API is public.

class List<T> {
    private T[] items;
    private int count;

    public List() {
        this.items = new T[4];
        this.count = 0;
    }

    public int size() { return this.count; }

    public void add(T x) {
        if (this.count == this.items.length) { this.grow(); }
        this.items[this.count] = x;
        this.count = this.count + 1;
    }

    public T get(int i) {
        if (i < 0) { panic("List.get: index out of range"); }
        if (i >= this.count) { panic("List.get: index out of range"); }
        return this.items[i];
    }

    public void set(int i, T x) {
        if (i < 0) { panic("List.set: index out of range"); }
        if (i >= this.count) { panic("List.set: index out of range"); }
        this.items[i] = x;
    }

    private void grow() {
        T[] bigger = new T[this.items.length * 2];
        int i = 0;
        while (i < this.count) { bigger[i] = this.items[i]; i = i + 1; }
        this.items = bigger;
    }
}

class Map<K, V> {
    private K[] keys;
    private V[] vals;
    private int count;

    public Map() {
        this.keys = new K[4];
        this.vals = new V[4];
        this.count = 0;
    }

    public int size() { return this.count; }

    private int indexOf(K key) {
        int i = 0;
        while (i < this.count) {
            if (this.keys[i] == key) { return i; }
            i = i + 1;
        }
        return -1;
    }

    public bool has(K key) { return this.indexOf(key) >= 0; }

    public V get(K key) {
        int i = this.indexOf(key);
        if (i >= 0) { return this.vals[i]; }
        V notfound;
        return notfound;
    }

    public void put(K key, V value) {
        int i = this.indexOf(key);
        if (i >= 0) { this.vals[i] = value; return; }
        if (this.count == this.keys.length) { this.grow(); }
        this.keys[this.count] = key;
        this.vals[this.count] = value;
        this.count = this.count + 1;
    }

    private void grow() {
        K[] bk = new K[this.keys.length * 2];
        V[] bv = new V[this.vals.length * 2];
        int i = 0;
        while (i < this.count) {
            bk[i] = this.keys[i]; bv[i] = this.vals[i]; i = i + 1;
        }
        this.keys = bk;
        this.vals = bv;
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m27.py -q`
Expected: PASS (all M27 tests).

- [ ] **Step 5: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tawla/stdlib/Collections.twl tests/test_m27.py
git commit -m "Add Collections.twl with List and Map"
```

---

## Task 4: Example, README, final verification

**Files:**
- Create: `examples/collections.twl`
- Modify: `README.md`

- [ ] **Step 1: Write the example** — Create `examples/collections.twl`:

```tawla
// List and Map from the standard library.
import "Collections.twl";

class Main {
    void main() {
        List<int> squares = new List<int>();
        for (int i = 1; i <= 5; i = i + 1) {
            squares.add(i * i);
        }
        print(squares.size());        // 5
        print(squares.get(4));        // 25

        Map<string, int> ages = new Map<string, int>();
        ages.put("ada", 36);
        ages.put("bob", 7);
        print(ages.get("ada"));       // 36
        if (ages.has("carol")) { print(1); } else { print(0); }  // 0
    }
}
```

- [ ] **Step 2: Run the example**

Run: `./venv/Scripts/python -m tawla run examples/collections.twl`
Expected output:
```
5
25
36
0
```

- [ ] **Step 3: Add a README bullet** — In `README.md`, under "What the language can do", after the IO library bullet:

```markdown
- **Collections:** `import "Collections.twl";` gives you a growable `List<T>`
  (`add`, `get`, `set`, `size`) and a `Map<K,V>` (`put`, `get`, `has`, `size`).
  `Map.get` returns `null` for a missing object value. (No nested generics yet,
  e.g. `Map<string, List<int>>`.)
- **`panic(s)`:** print a message and abort, for unrecoverable errors.
```

- [ ] **Step 4: Final full-suite run**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add examples/collections.twl README.md
git commit -m "Add collections example and README note"
```

---

## Self-review

**Spec coverage:**
- `List<T>` add/get/set/size → Task 3 (`Collections.twl`) + Task 3 tests. ✓
- `Map<K,V>` put/get/has/size → Task 3 + tests. ✓
- `List` out-of-range → `panic` → Task 1 (builtin) + Task 3 test `test_list_out_of_range_panics`. ✓
- `Map.get` missing → `null` (ref) / zero (value) via default-init → Task 3 tests `test_map_missing_value_type_is_zero` / `test_map_missing_reference_type_is_null`. ✓
- string keys match by value → exercised by `test_map_basic`/`test_map_overwrite` (string `==`). ✓
- `panic(string)` builtin → Task 1. ✓
- Parser fix for `List<int> xs` → Task 2; `var` form unchanged (still works). ✓
- Bundled via stdlib search path + `package-data` → no new packaging needed (existing `stdlib/*.twl` rule); verified by tests importing `Collections.twl`. ✓
- Example + README → Task 4. ✓
- Limitations (nested generics, O(n), identity keys) → documented in README/spec; not implemented (correct). ✓

**Placeholder scan:** No TBD/TODO; every code/test step shows full content; commands have expected output.

**Type consistency:** `panic` is `([STRING], VOID)` in sema and emitted in `_gen_builtin` consistently. `_generic_decl_ahead` is defined and called from `_is_decl_start`. `Collections.twl` method names (`add`/`get`/`set`/`size`/`put`/`has`/`indexOf`/`grow`) match the tests' call sites. `List`/`Map` constructors are no-arg and `public`. ✓
