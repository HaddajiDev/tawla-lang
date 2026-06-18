# Backend Essentials (`Sys.twl` / `Fs.twl` / `Crypto.twl`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add env vars, time/sleep, UUID, file I/O, and hashing/HMAC to Tawla as three themed stdlib modules over one new runtime.

**Architecture:** One Python-hosted `sys_runtime.py` (over `os`/`time`/`uuid`/`hashlib`/`hmac`) registered with the JIT via `llvm.add_symbol`, like `sqlite_runtime`. 12 `__*` builtins wired through sema + codegen; `Sys.twl`/`Fs.twl`/`Crypto.twl` wrap them as free functions. File errors return a sentinel + stashed message, and the `Fs.twl` wrapper does `throw __fs_error()` (catchable).

**Tech Stack:** Python 3.11+ stdlib, llvmlite, the Tawla compiler, pytest.

## Global Constraints

- Use `venv/Scripts/python.exe` for everything; tests via `venv/Scripts/python.exe -m pytest`.
- Final version: `1.8.0` (`pyproject.toml` line 3, `tawla/__init__.py` line 3).
- `nowMillis()` returns **float** (epoch-millis overflows Tawla's 32-bit int); `now()` returns int seconds.

**Reference spec:** `docs/superpowers/specs/2026-06-17-backend-essentials-design.md`

---

## Verified facts (from the codebase)

- Runtime model: `tawla/sqlite_runtime.py` / `tawla/fetch_runtime.py` — `_alloc(s)` GC-allocates a NUL-terminated string (returns int address) via `from .gc_runtime import HEAP`; returning `0` is a null `char*`. String args reach `CFUNCTYPE` wrappers as `c_char_p` (bytes), decoded with a helper. `install()` `llvm.add_symbol`s each and the module is added to `compiler.py`'s runtime imports + `run_file` install list.
- sema `_BUILTINS` maps `name -> (param_types, return_type)` with `INT/FLOAT/STRING/VOID`. Float builtins use `FLOAT`; void use `VOID` (e.g. `"__sleep..."`-style and `"__http_respond": (..., VOID)`).
- codegen: type constants `i32`, `i8ptr`, `f64`, `void`. Externs declared as `ir.Function(self.module, ir.FunctionType(ret, [args]), name="__x")` near the `__sql_*` block; dispatched in the `_gen_builtin_call` `if name == "...":` chain (after the `__sql_*` cases). A void builtin may `return self.builder.call(...)`. `self._gen_expr(args[i])` yields the arg value.
- `gc_runtime.HEAP` is a module-global usable directly (so `_alloc` works in a Python-level test; read it back with `ctypes.string_at(addr)`).
- `tests/conftest.py` `run_twl(src)` runs `python -m tawla run <file>` in a subprocess from repo root, inheriting `os.environ` (so `monkeypatch.setenv` is visible to the child). On Windows, `open()` accepts forward-slash paths.
- stdlib `.twl` files bundle via `[tool.setuptools.package-data] tawla = ["stdlib/*.twl"]`. `tawlac.spec` has a `hiddenimports += [...]` list.

## File Structure

| File | Change |
|------|--------|
| `tawla/sys_runtime.py` | New — env/time/uuid/file/hash functions + ctypes wrappers + `install()` |
| `tawla/compiler.py` | Register `sys_runtime.install()` |
| `tawla/sema.py` | Declare the 12 `__*` builtins |
| `tawla/codegen.py` | Declare + dispatch the 12 builtins |
| `tawla/stdlib/Sys.twl`, `Fs.twl`, `Crypto.twl` | New stdlib modules |
| `tawlac.spec` | Add `tawla.sys_runtime` to `hiddenimports` |
| `tests/test_m39.py`; `examples/essentials.twl`; README; docs; `pyproject.toml`; `tawla/__init__.py` | Tests, example, docs, version |

---

## Task 1: `sys_runtime.py` + compiler wiring

**Files:** Create `tawla/sys_runtime.py`; modify `tawla/compiler.py`; create `tests/test_m39.py`.

**Interfaces — Produces:** module `tawla.sys_runtime` with `install()` and the
functions `_env_get(name)->int(addr)|0`, `_time_secs()->int`,
`_time_millis()->float`, `_sleep_millis(ms)`, `_uuid()->int(addr)`,
`_file_read(path)->int(addr)|0`, `_file_write(path,content)->int`,
`_file_append(path,content)->int`, `_file_exists(path)->int`,
`_fs_error()->int(addr)`, `_sha256(s)->int(addr)`,
`_hmac_sha256(key,msg)->int(addr)`. Symbols registered: `__env_get,
__time_secs, __time_millis, __sleep_millis, __uuid, __file_read, __file_write,
__file_append, __file_exists, __fs_error, __sha256, __hmac_sha256`.

- [ ] **Step 1: Write the failing runtime test**

Create `tests/test_m39.py`:

```python
"""M39: backend essentials (Sys.twl / Fs.twl / Crypto.twl)."""

import ctypes
import hashlib
import hmac


def test_sys_runtime_functions(tmp_path):
    from tawla import sys_runtime as S

    assert S._time_secs() > 1_700_000_000
    assert S._time_millis() > 1_700_000_000_000.0

    u = ctypes.string_at(S._uuid()).decode()
    assert len(u) == 36 and "-" in u

    assert ctypes.string_at(S._sha256("abc")).decode() == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    expect = hmac.new(b"key", b"msg", hashlib.sha256).hexdigest()
    assert ctypes.string_at(S._hmac_sha256("key", "msg")).decode() == expect

    p = str(tmp_path / "f.txt")
    assert S._file_write(p, "hello") == 0
    assert S._file_append(p, " world") == 0
    assert ctypes.string_at(S._file_read(p)).decode() == "hello world"
    assert S._file_exists(p) == 1
    assert S._file_exists(str(tmp_path / "missing")) == 0
    assert S._file_read(str(tmp_path / "missing")) == 0   # error -> null
    assert S._fs_error() != 0                              # message stashed

    import os
    os.environ["TAWLA_TEST_VAR"] = "xyz"
    assert ctypes.string_at(S._env_get("TAWLA_TEST_VAR")).decode() == "xyz"
    assert S._env_get("TAWLA_DEFINITELY_UNSET_VAR_123") == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_m39.py -v`
Expected: FAIL — `tawla.sys_runtime` doesn't exist.

- [ ] **Step 3: Create the runtime**

Create `tawla/sys_runtime.py`:

```python
"""Backend essentials for Tawla's Sys.twl / Fs.twl / Crypto.twl, hosted in
Python and handed to the JIT via llvmlite's add_symbol (like sqlite_runtime).

File operations return a sentinel and stash the error message; Fs.twl turns a
failure into a Tawla throw (the runtime can't unwind JIT frames itself).
"""

import ctypes
import hashlib
import hmac
import os
import time
import uuid

import llvmlite.binding as llvm

from .gc_runtime import HEAP

_last_fs_error = ""


def _alloc(s):
    data = s.encode("utf-8") + b"\x00"
    addr = HEAP.alloc(len(data))
    ctypes.memmove(addr, data, len(data))
    return addr


def _dec(b):
    return b.decode("utf-8") if b else ""


def _env_get(name):
    v = os.environ.get(name)
    return _alloc(v) if v is not None else 0


def _time_secs():
    return int(time.time())


def _time_millis():
    return time.time() * 1000.0


def _sleep_millis(ms):
    time.sleep(ms / 1000.0)


def _uuid():
    return _alloc(str(uuid.uuid4()))


def _file_read(path):
    global _last_fs_error
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _alloc(f.read())
    except OSError as e:
        _last_fs_error = str(e)
        return 0


def _file_write(path, content):
    global _last_fs_error
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return 0
    except OSError as e:
        _last_fs_error = str(e)
        return 1


def _file_append(path, content):
    global _last_fs_error
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
        return 0
    except OSError as e:
        _last_fs_error = str(e)
        return 1


def _file_exists(path):
    return 1 if os.path.exists(path) else 0


def _fs_error():
    return _alloc(_last_fs_error)


def _sha256(s):
    return _alloc(hashlib.sha256(s.encode("utf-8")).hexdigest())


def _hmac_sha256(key, message):
    return _alloc(
        hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    )


_c_env_get = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p)(lambda n: _env_get(_dec(n)))
_c_time_secs = ctypes.CFUNCTYPE(ctypes.c_int32)(lambda: _time_secs())
_c_time_millis = ctypes.CFUNCTYPE(ctypes.c_double)(lambda: _time_millis())
_c_sleep_millis = ctypes.CFUNCTYPE(None, ctypes.c_int32)(lambda ms: _sleep_millis(ms))
_c_uuid = ctypes.CFUNCTYPE(ctypes.c_void_p)(lambda: _uuid())
_c_file_read = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p)(lambda p: _file_read(_dec(p)))
_c_file_write = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_char_p, ctypes.c_char_p)(
    lambda p, c: _file_write(_dec(p), _dec(c))
)
_c_file_append = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_char_p, ctypes.c_char_p)(
    lambda p, c: _file_append(_dec(p), _dec(c))
)
_c_file_exists = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_char_p)(lambda p: _file_exists(_dec(p)))
_c_fs_error = ctypes.CFUNCTYPE(ctypes.c_void_p)(lambda: _fs_error())
_c_sha256 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p)(lambda s: _sha256(_dec(s)))
_c_hmac_sha256 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p)(
    lambda k, m: _hmac_sha256(_dec(k), _dec(m))
)

_CALLBACKS = [
    _c_env_get, _c_time_secs, _c_time_millis, _c_sleep_millis, _c_uuid,
    _c_file_read, _c_file_write, _c_file_append, _c_file_exists, _c_fs_error,
    _c_sha256, _c_hmac_sha256,
]
_registered = False


def install():
    """Register the essentials primitives with llvmlite, then reset state."""
    global _registered, _last_fs_error
    if not _registered:
        cast = ctypes.cast
        llvm.add_symbol("__env_get", cast(_c_env_get, ctypes.c_void_p).value)
        llvm.add_symbol("__time_secs", cast(_c_time_secs, ctypes.c_void_p).value)
        llvm.add_symbol("__time_millis", cast(_c_time_millis, ctypes.c_void_p).value)
        llvm.add_symbol("__sleep_millis", cast(_c_sleep_millis, ctypes.c_void_p).value)
        llvm.add_symbol("__uuid", cast(_c_uuid, ctypes.c_void_p).value)
        llvm.add_symbol("__file_read", cast(_c_file_read, ctypes.c_void_p).value)
        llvm.add_symbol("__file_write", cast(_c_file_write, ctypes.c_void_p).value)
        llvm.add_symbol("__file_append", cast(_c_file_append, ctypes.c_void_p).value)
        llvm.add_symbol("__file_exists", cast(_c_file_exists, ctypes.c_void_p).value)
        llvm.add_symbol("__fs_error", cast(_c_fs_error, ctypes.c_void_p).value)
        llvm.add_symbol("__sha256", cast(_c_sha256, ctypes.c_void_p).value)
        llvm.add_symbol("__hmac_sha256", cast(_c_hmac_sha256, ctypes.c_void_p).value)
        _registered = True
    _last_fs_error = ""
```

- [ ] **Step 4: Run the runtime test**

Run: `venv/Scripts/python.exe -m pytest tests/test_m39.py -v`
Expected: PASS.

- [ ] **Step 5: Wire into the compiler**

In `tawla/compiler.py`, add `sys_runtime` to the runtime import block (alphabetical, after `str_runtime` or wherever it fits) and call its install in `run_file` after `sqlite_runtime.install()`:

```python
    sqlite_runtime.install()
    sys_runtime.install()
```

(Add `sys_runtime` to the `from . import (...)` list.)

- [ ] **Step 6: Commit**

```bash
git add tawla/sys_runtime.py tawla/compiler.py tests/test_m39.py
git commit -m "sys_runtime: env/time/uuid/file/hash primitives; wire into compiler"
```

---

## Task 2: Wire the 12 builtins (sema + codegen)

**Files:** Modify `tawla/sema.py`, `tawla/codegen.py`; test `tests/test_m39.py`.

**Interfaces — Consumes:** the `__*` symbols from Task 1. **Produces:** the 12 builtins callable from Tawla.

- [ ] **Step 1: Write the failing end-to-end test**

Append to `tests/test_m39.py`:

```python
def test_sys_builtins_end_to_end(run_twl):
    src = (
        "class Main { void main() {"
        ' print(__sha256("abc"));'
        ' print(__file_exists("definitely_missing_xyz"));'
        " } }"
    )
    assert run_twl(src).stdout == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n0\n"
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_m39.py::test_sys_builtins_end_to_end -v`
Expected: FAIL — sema rejects the unknown builtins.

- [ ] **Step 3: Declare the builtins in sema**

In `tawla/sema.py` `_BUILTINS`, after the `__sql_*` entries, add:

```python
    "__env_get": ([STRING], STRING),
    "__time_secs": ([], INT),
    "__time_millis": ([], FLOAT),
    "__sleep_millis": ([INT], VOID),
    "__uuid": ([], STRING),
    "__file_read": ([STRING], STRING),
    "__file_write": ([STRING, STRING], INT),
    "__file_append": ([STRING, STRING], INT),
    "__file_exists": ([STRING], INT),
    "__fs_error": ([], STRING),
    "__sha256": ([STRING], STRING),
    "__hmac_sha256": ([STRING, STRING], STRING),
```

- [ ] **Step 4: Declare the functions in codegen**

In `tawla/codegen.py`, after the `self.sql_*` extern declarations, add:

```python
        self.env_get = ir.Function(self.module, ir.FunctionType(i8ptr, [i8ptr]), name="__env_get")
        self.time_secs = ir.Function(self.module, ir.FunctionType(i32, []), name="__time_secs")
        self.time_millis = ir.Function(self.module, ir.FunctionType(f64, []), name="__time_millis")
        self.sleep_millis = ir.Function(self.module, ir.FunctionType(void, [i32]), name="__sleep_millis")
        self.sys_uuid = ir.Function(self.module, ir.FunctionType(i8ptr, []), name="__uuid")
        self.file_read = ir.Function(self.module, ir.FunctionType(i8ptr, [i8ptr]), name="__file_read")
        self.file_write = ir.Function(self.module, ir.FunctionType(i32, [i8ptr, i8ptr]), name="__file_write")
        self.file_append = ir.Function(self.module, ir.FunctionType(i32, [i8ptr, i8ptr]), name="__file_append")
        self.file_exists = ir.Function(self.module, ir.FunctionType(i32, [i8ptr]), name="__file_exists")
        self.fs_error = ir.Function(self.module, ir.FunctionType(i8ptr, []), name="__fs_error")
        self.sha256 = ir.Function(self.module, ir.FunctionType(i8ptr, [i8ptr]), name="__sha256")
        self.hmac_sha256 = ir.Function(self.module, ir.FunctionType(i8ptr, [i8ptr, i8ptr]), name="__hmac_sha256")
```

- [ ] **Step 5: Dispatch the builtins**

In `tawla/codegen.py`, in the `_gen_builtin_call` chain after the `__sql_*` cases, add:

```python
        if name == "__env_get":
            return self.builder.call(self.env_get, [self._gen_expr(args[0])])
        if name == "__time_secs":
            return self.builder.call(self.time_secs, [])
        if name == "__time_millis":
            return self.builder.call(self.time_millis, [])
        if name == "__sleep_millis":
            return self.builder.call(self.sleep_millis, [self._gen_expr(args[0])])
        if name == "__uuid":
            return self.builder.call(self.sys_uuid, [])
        if name == "__file_read":
            return self.builder.call(self.file_read, [self._gen_expr(args[0])])
        if name == "__file_write":
            return self.builder.call(self.file_write, [self._gen_expr(args[0]), self._gen_expr(args[1])])
        if name == "__file_append":
            return self.builder.call(self.file_append, [self._gen_expr(args[0]), self._gen_expr(args[1])])
        if name == "__file_exists":
            return self.builder.call(self.file_exists, [self._gen_expr(args[0])])
        if name == "__fs_error":
            return self.builder.call(self.fs_error, [])
        if name == "__sha256":
            return self.builder.call(self.sha256, [self._gen_expr(args[0])])
        if name == "__hmac_sha256":
            return self.builder.call(self.hmac_sha256, [self._gen_expr(args[0]), self._gen_expr(args[1])])
```

- [ ] **Step 6: Run the test**

Run: `venv/Scripts/python.exe -m pytest tests/test_m39.py -v`
Expected: PASS (both tests).

- [ ] **Step 7: Commit**

```bash
git add tawla/sema.py tawla/codegen.py tests/test_m39.py
git commit -m "Wire backend-essentials builtins (sema + codegen)"
```

---

## Task 3: `Sys.twl` / `Fs.twl` / `Crypto.twl` + full tests

**Files:** Create `tawla/stdlib/Sys.twl`, `tawla/stdlib/Fs.twl`, `tawla/stdlib/Crypto.twl`; test `tests/test_m39.py`.

**Interfaces — Consumes:** the 12 builtins from Task 2.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_m39.py`:

```python
def test_sys_getenv(run_twl, monkeypatch):
    monkeypatch.setenv("TAWLA_TEST_ENV", "hello")
    src = 'import "Sys.twl"; class Main { void main() { print(getenv("TAWLA_TEST_ENV")); } }'
    assert run_twl(src).stdout == "hello\n"


def test_sys_getenv_absent(run_twl):
    src = (
        'import "Sys.twl"; class Main { void main() {'
        ' string v = getenv("TAWLA_UNSET_XYZ_123");'
        ' if (v == null) { print("null"); } } }'
    )
    assert run_twl(src).stdout == "null\n"


def test_sys_uuid_and_time(run_twl):
    src = (
        'import "Sys.twl"; class Main { void main() {'
        " string u = uuid(); print(u.length);"
        " int t = now(); if (t > 1700000000) { print(\"ok\"); }"
        " float m = nowMillis(); if (m > 1700000000000.0) { print(\"big\"); }"
        " sleepMillis(10); print(\"slept\"); } }"
    )
    assert run_twl(src).stdout == "36\nok\nbig\nslept\n"


def test_fs_roundtrip(run_twl, tmp_path):
    p = str(tmp_path / "data.txt").replace("\\", "/")
    body = (
        f'writeFile("{p}", "abc"); appendFile("{p}", "def");'
        f' print(readFile("{p}"));'
        f' if (exists("{p}")) {{ print("yes"); }}'
    )
    src = 'import "Fs.twl"; class Main { void main() { ' + body + " } }"
    assert run_twl(src).stdout == "abcdef\nyes\n"


def test_fs_read_error_is_catchable(run_twl, tmp_path):
    p = str(tmp_path / "missing.txt").replace("\\", "/")
    body = (
        f'fuck_around {{ readFile("{p}"); print("ran"); }}'
        ' find_out (e) { print("caught"); }'
    )
    src = 'import "Fs.twl"; class Main { void main() { ' + body + " } }"
    assert run_twl(src).stdout == "caught\n"


def test_crypto(run_twl):
    import hashlib
    import hmac
    expect = hmac.new(b"key", b"msg", hashlib.sha256).hexdigest()
    src = (
        'import "Crypto.twl"; class Main { void main() {'
        ' print(sha256("abc")); print(hmacSha256("key", "msg")); } }'
    )
    out = run_twl(src).stdout
    assert out == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n" + expect + "\n"
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_m39.py -k "getenv or uuid or fs or crypto" -v`
Expected: FAIL — the modules don't exist, so the imports fail.

- [ ] **Step 3: Create `Sys.twl`**

Create `tawla/stdlib/Sys.twl`:

```tawla
// System essentials: environment, time, and UUIDs. Import with: import "Sys.twl";

// Environment variable value, or null if it isn't set.
string getenv(string name) { return __env_get(name); }

// Current time as epoch seconds.
int now() { return __time_secs(); }

// Current time as epoch milliseconds (a float, since it exceeds a 32-bit int).
float nowMillis() { return __time_millis(); }

// Pause execution for the given number of milliseconds.
void sleepMillis(int ms) { __sleep_millis(ms); }

// A random UUID (dashed v4 form).
string uuid() { return __uuid(); }
```

- [ ] **Step 4: Create `Fs.twl`**

Create `tawla/stdlib/Fs.twl`:

```tawla
// File I/O. Import with: import "Fs.twl";
// read/write/append throw on failure — catch with fuck_around / find_out.

string readFile(string path) {
    string c = __file_read(path);
    if (c == null) { throw __fs_error(); }
    return c;
}

void writeFile(string path, string content) {
    if (__file_write(path, content) != 0) { throw __fs_error(); }
}

void appendFile(string path, string content) {
    if (__file_append(path, content) != 0) { throw __fs_error(); }
}

bool exists(string path) { return __file_exists(path) != 0; }
```

- [ ] **Step 5: Create `Crypto.twl`**

Create `tawla/stdlib/Crypto.twl`:

```tawla
// Hashing. Import with: import "Crypto.twl";

// Lowercase hex SHA-256 of the string's UTF-8 bytes.
string sha256(string s) { return __sha256(s); }

// Lowercase hex HMAC-SHA-256 — for signing tokens, sessions, and webhooks.
string hmacSha256(string key, string message) { return __hmac_sha256(key, message); }
```

- [ ] **Step 6: Run the tests**

Run: `venv/Scripts/python.exe -m pytest tests/test_m39.py -v`
Expected: PASS (all M39 tests).

- [ ] **Step 7: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all pass, no regressions.

- [ ] **Step 8: Commit**

```bash
git add tawla/stdlib/Sys.twl tawla/stdlib/Fs.twl tawla/stdlib/Crypto.twl tests/test_m39.py
git commit -m "Add Sys.twl / Fs.twl / Crypto.twl over the essentials builtins"
```

---

## Task 4: Example, docs, spec hiddenimport, version, verification

**Files:** Create `examples/essentials.twl`; modify `tawlac.spec`, `README.md`, `tawla_lang_docs/index.html`, `pyproject.toml`, `tawla/__init__.py`.

- [ ] **Step 1: Create the example**

Create `examples/essentials.twl`:

```tawla
// Backend essentials: env vars, time, UUIDs, file I/O, and hashing.
import "Sys.twl";
import "Fs.twl";
import "Crypto.twl";

class Main {
    void main() {
        // a request id + a signed token
        string id = uuid();
        print("request " + id);
        print("sig " + hmacSha256("secret-key", id));

        // write a log line, read it back
        string line = "[" + toString(now()) + "] handled " + id + "\n";
        writeFile("essentials.log", line);
        print("log: " + readFile("essentials.log"));

        // a config value with a fallback
        string mode = getenv("APP_MODE");
        if (mode == null) { mode = "dev"; }
        print("mode " + mode);
    }
}
```

- [ ] **Step 2: Verify the example runs**

Run: `venv/Scripts/python.exe -m tawla run examples/essentials.twl`
Expected: prints `request <uuid>`, `sig <64-hex>`, `log: [<secs>] handled <uuid>`,
and `mode dev` (assuming `APP_MODE` is unset). Then remove the stray log:
`rm -f essentials.log`.

- [ ] **Step 3: Add the runtime to the PyInstaller spec**

In `tawlac.spec`, add `"tawla.sys_runtime"` to the `hiddenimports += [...]` list.

- [ ] **Step 4: Update the README**

In `README.md`, add a bullet in the "What the language can do" list, after the SQLite bullet:

```markdown
- **Backend essentials:** `import "Sys.twl";` (`getenv`, `now`/`nowMillis`/`sleepMillis`,
  `uuid`), `import "Fs.twl";` (`readFile`/`writeFile`/`appendFile` — throwing —
  and `exists`), and `import "Crypto.twl";` (`sha256`, `hmacSha256`). The basics
  for config, logging, IDs, and signing.
```

- [ ] **Step 5: Update the docs site**

In `tawla_lang_docs/index.html`, add a `#essentials` section after the `#sql`
section (and a sidebar link `<a href="#essentials">Essentials</a>` in the
Standard library nav group). Intro + this example (escape `<`/`>`/`&`):

```html
    <section id="essentials">
      <h2>Backend essentials</h2>
      <p>Three small modules cover what services need day to day. <code>import "Sys.twl";</code> gives <code>getenv</code>, <code>now()</code> / <code>nowMillis()</code> / <code>sleepMillis(ms)</code>, and <code>uuid()</code>. <code>import "Fs.twl";</code> gives <code>readFile</code> / <code>writeFile</code> / <code>appendFile</code> (which throw on failure) and <code>exists</code>. <code>import "Crypto.twl";</code> gives <code>sha256(s)</code> and <code>hmacSha256(key, message)</code> for signing.</p>
      <div class="code">
        <div class="code-head"><span class="dot"></span><span class="fname">essentials.twl</span><button class="copy-btn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg><span class="copy-label">Copy</span></button></div>
        <pre><code class="twl">string id = uuid();
string sig = hmacSha256("secret-key", id);
writeFile("audit.log", id + " " + sig + "\n");
string mode = getenv("APP_MODE");
if (mode == null) { mode = "dev"; }</code></pre>
      </div>
    </section>
```

- [ ] **Step 6: Bump the version to 1.8.0**

`pyproject.toml` line 3 → `version = "1.8.0"`; `tawla/__init__.py` line 3 →
`__version__ = "1.8.0"`.

- [ ] **Step 7: Full suite + version + frozen smoke**

Run: `venv/Scripts/python.exe -m pytest -q` → all pass.
Run: `venv/Scripts/python.exe -m tawla version` → `tawlac 1.8.0`.
Rebuild the binary and confirm the essentials work frozen:
```bash
venv/Scripts/pyinstaller.exe tawlac.spec --clean --noconfirm
./dist/tawlac.exe run examples/essentials.twl
rm -f essentials.log
```
Expected: the same `request`/`sig`/`log`/`mode dev` output.

- [ ] **Step 8: Commit (compiler) + push docs**

```bash
git add examples/essentials.twl tawlac.spec README.md pyproject.toml tawla/__init__.py
git commit -m "Add essentials example, docs, hiddenimport; bump to 1.8.0"
```

```bash
cd D:\Projects\tawla_lang_docs
git add index.html
git commit -m "Document backend essentials (Sys/Fs/Crypto)"
git push
cd D:\Projects\Tawla_lang
```

---

## Done criteria

- `getenv` (null if unset), `now`/`nowMillis`(float)/`sleepMillis`, `uuid`,
  `readFile`/`writeFile`/`appendFile` (throwing) + `exists`, `sha256`,
  `hmacSha256` all work; `sha256("abc")` matches the known digest.
- File errors throw and are catchable; uncaught read of a missing file exits non-zero.
- `tests/test_m39.py` + full suite green; `tawlac version` → `1.8.0`; the frozen
  binary runs `essentials.twl`.

## Release (on the user's go-ahead)

Merge to `main`, push, `git tag v1.8.0 && git push origin v1.8.0`, then build +
publish 1.8.0 to PyPI.
