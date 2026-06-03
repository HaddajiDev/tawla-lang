# String Utilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `charAt`, `substring`, `toInt`, `toFloat`, and `toString` as global builtins.

**Architecture:** All in codegen as builtins backed by C-library calls (`atoi`, `strtod`, `snprintf`, `memcpy`, plus existing `strlen`/`gc_alloc`) — no new Python runtime. `charAt`/`substring` are bounds-checked (reusing the abort pattern); `substring`/`toString` allocate result strings on the GC heap.

**Tech Stack:** Python 3.11+, llvmlite. Tests run via the `run_twl` subprocess fixture.

**Reference spec:** `docs/superpowers/specs/2026-06-02-string-utilities-design.md`

**Milestone:** M31 — additive, ships as **1.3.0** (release is a separate user-triggered step).

---

## File structure

- `tawla/sema.py` — builtin signatures (`charAt`/`substring`/`toInt`/`toFloat` fixed; `toString` overloaded).
- `tawla/codegen.py` — C externs + format globals + `_gen_builtin` branches.
- `tests/test_m31.py` — new tests.
- `examples/strings_util.twl`, `README.md` — example + note.

---

## Task 1: `charAt` and `substring`

**Files:**
- Modify: `tawla/sema.py`, `tawla/codegen.py`
- Test: `tests/test_m31.py`

- [ ] **Step 1: Write the failing tests** — Create `tests/test_m31.py`:

```python
"""M31: string utilities (charAt, substring, toInt, toFloat, toString)."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError


def _err(result):
    return result.stdout + result.stderr


def _main(body):
    return "class Main { void main() { " + body + " } }"


def test_char_at(run_twl):
    assert run_twl(_main('print(charAt("abc", 0)); print(charAt("abc", 2));')).stdout == "97\n99\n"


def test_char_at_out_of_range_aborts(run_twl):
    r = run_twl(_main('print(charAt("abc", 5));'))
    assert r.returncode != 0
    assert "out of range" in _err(r)


def test_substring(run_twl):
    assert run_twl(_main('print(substring("hello", 1, 4));')).stdout == "ell\n"


def test_substring_empty(run_twl):
    assert run_twl(_main('print(substring("hi", 0, 0));')).stdout == "\n"


def test_substring_full(run_twl):
    assert run_twl(_main('print(substring("hi", 0, 2));')).stdout == "hi\n"


def test_substring_out_of_range_aborts(run_twl):
    r = run_twl(_main('print(substring("hi", 0, 9));'))
    assert r.returncode != 0
    assert "out of range" in _err(r)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m31.py -q`
Expected: FAIL — sema "call to undefined function 'charAt'".

- [ ] **Step 3: Register the signatures in sema** — In `tawla/sema.py`, add to the `_BUILTINS` dict:

```python
    "charAt": ([STRING, INT], INT),
    "substring": ([STRING, INT, INT], STRING),
```

- [ ] **Step 4: Declare the C externs + message global** — In `tawla/codegen.py`, in `_declare_runtime`, after the existing `strcat`/`strcpy` declarations add:

```python
        self.memcpy = ir.Function(
            self.module, ir.FunctionType(i8ptr, [i8ptr, i8ptr, i64]), name="memcpy"
        )
        self.atoi = ir.Function(self.module, ir.FunctionType(i32, [i8ptr]), name="atoi")
        self.strtod = ir.Function(
            self.module, ir.FunctionType(f64, [i8ptr, i8ptr.as_pointer()]), name="strtod"
        )
        self.snprintf = ir.Function(
            self.module, ir.FunctionType(i32, [i8ptr, i64, i8ptr], var_arg=True), name="snprintf"
        )
```

And next to the other format-string globals (`self._fmt_int = ...`):

```python
        self._fmt_d = self._global_string(b"%d\0", "fmt_d")
        self._fmt_g = self._global_string(b"%g\0", "fmt_g")
        self._str_oob_msg = self._global_string(b"string index out of range\n\0", "str_oob_msg")
```

- [ ] **Step 5: Add a string-bounds-abort helper** — In `tawla/codegen.py`, add near `_null_check`:

```python
    def _str_oob(self, bad: ir.Value) -> None:
        """If `bad` (i1) is true, print the string-index message and exit."""
        func = self.builder.function
        err_bb = func.append_basic_block("str.oob")
        ok_bb = func.append_basic_block("str.ok")
        self.builder.cbranch(bad, err_bb, ok_bb)
        self.builder.position_at_end(err_bb)
        self.builder.call(self.printf, [self._str_ptr(self._str_oob_msg)])
        self.builder.call(self.exit, [ir.Constant(i32, 1)])
        self.builder.unreachable()
        self.builder.position_at_end(ok_bb)
```

- [ ] **Step 6: Emit `charAt` and `substring`** — In `_gen_builtin` (before the final `raise CodeGenError`):

```python
        if name == "charAt":
            s = self._gen_expr(args[0])
            i = self._gen_expr(args[1])
            length = self.builder.trunc(self.builder.call(self.strlen, [s]), i32)
            below = self.builder.icmp_signed("<", i, ir.Constant(i32, 0))
            above = self.builder.icmp_signed(">=", i, length)
            self._str_oob(self.builder.or_(below, above))
            ch = self.builder.load(self.builder.gep(s, [i], inbounds=True))
            return self.builder.zext(ch, i32)
        if name == "substring":
            s = self._gen_expr(args[0])
            start = self._gen_expr(args[1])
            end = self._gen_expr(args[2])
            length = self.builder.trunc(self.builder.call(self.strlen, [s]), i32)
            bad = self.builder.or_(
                self.builder.or_(
                    self.builder.icmp_signed("<", start, ir.Constant(i32, 0)),
                    self.builder.icmp_signed(">", end, length),
                ),
                self.builder.icmp_signed(">", start, end),
            )
            self._str_oob(bad)
            n = self.builder.sub(end, start)
            n64 = self.builder.sext(n, i64)
            buf = self.builder.call(self.gc_alloc, [self.builder.add(n64, ir.Constant(i64, 1))])
            src = self.builder.gep(s, [start], inbounds=True)
            self.builder.call(self.memcpy, [buf, src, n64])
            self.builder.store(ir.Constant(i8, 0), self.builder.gep(buf, [n], inbounds=True))
            return buf
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m31.py -q`
Expected: PASS (6 passed).

- [ ] **Step 8: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add tawla/sema.py tawla/codegen.py tests/test_m31.py
git commit -m "Add charAt and substring builtins"
```

---

## Task 2: `toInt`, `toFloat`, `toString`

**Files:**
- Modify: `tawla/sema.py`, `tawla/codegen.py`
- Test: `tests/test_m31.py`

- [ ] **Step 1: Write the failing tests** — Append to `tests/test_m31.py`:

```python
def test_to_int(run_twl):
    assert run_twl(_main('print(toInt("42")); print(toInt("-7"));')).stdout == "42\n-7\n"


def test_to_int_non_numeric_is_zero(run_twl):
    assert run_twl(_main('print(toInt("xyz"));')).stdout == "0\n"


def test_to_float(run_twl):
    assert run_twl(_main('print(toFloat("3.5"));')).stdout == "3.5\n"


def test_to_string_int(run_twl):
    assert run_twl(_main('print(toString(42));')).stdout == "42\n"


def test_to_string_float(run_twl):
    assert run_twl(_main('print(toString(3.5));')).stdout == "3.5\n"


def test_round_trip(run_twl):
    assert run_twl(_main('print(toInt(toString(123)));')).stdout == "123\n"


def test_to_string_requires_numeric():
    with pytest.raises(SemaError):
        run_source('class Main { void main() { string s = toString("x"); } }')


def test_to_int_requires_string():
    with pytest.raises(SemaError):
        run_source("class Main { void main() { int n = toInt(5); } }")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m31.py -q -k "to_int or to_float or to_string or round_trip"`
Expected: FAIL — undefined function `toInt` etc.

- [ ] **Step 3: Register `toInt`/`toFloat` in sema** — In `tawla/sema.py`, add to `_BUILTINS`:

```python
    "toInt": ([STRING], INT),
    "toFloat": ([STRING], FLOAT),
```

- [ ] **Step 4: Type-check `toString` (overloaded)** — In `tawla/sema.py`, in `_check_builtin`, add a branch (alongside the math builtins, before the final `return None`):

```python
        if name == "toString":
            self._check_numeric(name, args, 1)
            return STRING
```

- [ ] **Step 5: Emit `toInt`/`toFloat`/`toString`** — In `tawla/codegen.py`, in `_gen_builtin` (before the final `raise CodeGenError`):

```python
        if name == "toInt":
            return self.builder.call(self.atoi, [self._gen_expr(args[0])])
        if name == "toFloat":
            return self.builder.call(
                self.strtod, [self._gen_expr(args[0]), ir.Constant(i8ptr.as_pointer(), None)]
            )
        if name == "toString":
            v = self._gen_expr(args[0])
            if v.type == f64:
                buf = self.builder.call(self.gc_alloc, [ir.Constant(i64, 32)])
                self.builder.call(
                    self.snprintf, [buf, ir.Constant(i64, 32), self._str_ptr(self._fmt_g), v]
                )
            else:
                buf = self.builder.call(self.gc_alloc, [ir.Constant(i64, 16)])
                self.builder.call(
                    self.snprintf, [buf, ir.Constant(i64, 16), self._str_ptr(self._fmt_d), v]
                )
            return buf
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m31.py -q`
Expected: PASS (all M31 tests).

- [ ] **Step 7: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tawla/sema.py tawla/codegen.py tests/test_m31.py
git commit -m "Add toInt, toFloat, and toString builtins"
```

---

## Task 3: Example, README, final verification

**Files:**
- Create: `examples/strings_util.twl`
- Modify: `README.md`

- [ ] **Step 1: Write the example** — Create `examples/strings_util.twl`:

```tawla
// String utilities: charAt, substring, toInt, toFloat, toString.

class Main {
    void main() {
        string s = "hello";
        print(s.length);                 // 5
        print(charAt(s, 0));             // 104  (code for 'h')
        print(substring(s, 1, 4));       // ell

        int n = toInt("40") + 2;
        print(toString(n));              // 42

        float f = toFloat("1.5") * 2.0;
        print(toString(f));              // 3
    }
}
```

- [ ] **Step 2: Run the example**

Run: `./venv/Scripts/python -m tawla run examples/strings_util.twl`
Expected output:
```
5
104
ell
42
3
```

- [ ] **Step 3: Add a README bullet** — In `README.md`, under "What the language can do", update/extend the strings bullet by adding after it:

```markdown
- **String utilities:** `charAt(s, i)` (character code), `substring(s, a, b)`,
  `toInt(s)` / `toFloat(s)`, and `toString(n)` (number to string).
```

- [ ] **Step 4: Final full-suite run**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add examples/strings_util.twl README.md
git commit -m "Add string-utilities example and README note"
```

---

## Self-review

**Spec coverage:**
- `charAt` (code, bounds-checked) → Task 1 + `test_char_at*`. ✓
- `substring` ([start,end), GC string, bounds-checked) → Task 1 + `test_substring*`. ✓
- `toInt`/`toFloat` (atoi/strtod) → Task 2 + tests. ✓
- `toString` (overloaded int/float via snprintf) → Task 2 (sema `_check_builtin` + codegen type-directed) + tests. ✓
- C externs (`atoi`/`strtod`/`snprintf`/`memcpy`) + format globals + GC allocation → Task 1 Step 4 / Task 2 Step 5. ✓
- abort on out-of-range → Task 1 `_str_oob` + tests. ✓
- sema type errors → Task 2 `test_to_string_requires_numeric` / `test_to_int_requires_string`. ✓
- Example + README → Task 3. ✓

**Placeholder scan:** No TBD/TODO; every code/test step shows full content; commands have expected output.

**Type consistency:** Builtin names match across sema `_BUILTINS`/`_check_builtin` and codegen `_gen_builtin` (`charAt`/`substring`/`toInt`/`toFloat`/`toString`). Externs (`self.memcpy`/`self.atoi`/`self.strtod`/`self.snprintf`) declared in Task 1 Step 4 and used in Tasks 1–2. `_str_oob` defined in Task 1 Step 5, used in Step 6. `self._fmt_d`/`self._fmt_g`/`self._str_oob_msg` globals defined Task 1 Step 4. `_check_numeric` is the existing math-builtin helper. ✓
