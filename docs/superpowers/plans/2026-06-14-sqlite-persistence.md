# SQLite Persistence (`Sql.twl`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add embedded SQLite to Tawla as a `Sql.twl` stdlib module — `Db`/`Stmt`/`Rows` with prepared statements, typed parameter binding, a row cursor, and catchable SQL errors.

**Architecture:** A Python-hosted `sqlite_runtime.py` (over the `sqlite3` module) registered with the JIT via `llvm.add_symbol`, exactly like `fetch_runtime`. 14 `__sql_*` builtins are wired through sema + codegen. `Sql.twl` wraps them in `Db`/`Stmt`/`Rows`; fallible ops return a status code and stash the error message, and the wrapper does `throw __sql_error()` so failures become catchable Tawla exceptions.

**Tech Stack:** Python 3.11+ (`sqlite3`), llvmlite, the Tawla compiler, pytest.

## Global Constraints

- Use `venv/Scripts/python.exe` for everything; run tests with `venv/Scripts/python.exe -m pytest`.
- Final version: `1.7.0` (`pyproject.toml` line 3, `tawla/__init__.py` line 3).
- Builtins are `__`-prefixed and callable from stdlib `.twl` code (like `__http_*`).

**Reference spec:** `docs/superpowers/specs/2026-06-14-sqlite-persistence-design.md`

---

## Verified facts (from the codebase)

- Runtime model: `tawla/fetch_runtime.py` — a `FetchState` with integer ids, `_alloc(s)` (GC string via `HEAP.alloc` + `memmove`), ctypes `CFUNCTYPE` wrappers, a `_CALLBACKS` list, and `install()` that `llvm.add_symbol`s each and calls `STATE.reset()`.
- `tawla/compiler.py` `run_file` installs runtimes (~lines 61-66): `gc_runtime.install(); eh_runtime.install(); io_runtime.install(); http_runtime.install(); str_runtime.install(); fetch_runtime.install()`.
- sema `_BUILTINS` dict maps name → `(param_types, return_type)`; `INT`, `FLOAT`, `STRING`, `VOID` are module constants. Examples: `"__http_respond": ([INT, INT, STRING, STRING], VOID)`, `"__http_query": ([INT, STRING], STRING)`.
- codegen: type constants `i32`, `i8ptr`, `f64 = ir.DoubleType()`, `void = ir.VoidType()`. Float builtins declared with `f64` (e.g. `self.libm_sqrt = ir.Function(self.module, ir.FunctionType(f64,[f64]), name="sqrt")`). `self._as_f64(expr)` coerces an **AST arg** to f64 (used as `self._as_f64(args[0])`). The builtin dispatch is the `if name == "...":` chain in `_gen_builtin_call`; multi-arg/void example `__http_respond` (~line 1028).
- Tawla string literal args reach builtins as `i8ptr`; `self._gen_expr(argN)` yields the value.
- stdlib `.twl` files are bundled via `pyproject.toml` `[tool.setuptools.package-data] tawla = ["stdlib/*.twl"]`, so a new `Sql.twl` ships automatically.
- `tawlac.spec` has a `hiddenimports += [...]` list of `tawla.*_runtime` modules.
- `tests/conftest.py` `run_twl(src)` runs `python -m tawla run <file>` in a subprocess from repo root and returns a `CompletedProcess` (`.stdout`, `.returncode`, `.stderr`).

## File Structure

| File | Change |
|------|--------|
| `tawla/sqlite_runtime.py` | New — `SqlState` + 14 ctypes wrappers + `install()` |
| `tawla/compiler.py` | Register `sqlite_runtime.install()` |
| `tawla/sema.py` | Declare the 14 `__sql_*` builtins |
| `tawla/codegen.py` | Declare + dispatch the 14 builtins |
| `tawla/stdlib/Sql.twl` | New — `Db`, `Stmt`, `Rows` |
| `tawlac.spec` | Add `tawla.sqlite_runtime` to `hiddenimports` |
| `tests/test_m38.py` | New tests |
| `examples/sql_demo.twl`, `README.md`, docs, `pyproject.toml`, `tawla/__init__.py` | Example, docs, version |

---

## Task 1: `sqlite_runtime.py` + compiler wiring

**Files:** Create `tawla/sqlite_runtime.py`; modify `tawla/compiler.py`; create `tests/test_m38.py`.

**Interfaces — Produces:** module `tawla.sqlite_runtime` with `STATE` (a `SqlState`) and `install()`. `SqlState` methods: `open(path)->int`, `prepare(cid,sql)->int`, `bind_int/bind_float/bind_str(sid,i,v)`, `exec(sid)->int` (0 ok / 1 err), `query(sid)->int` (rid / -1), `next(rid)->int`, `col_index(rid,name)->int`, `col_int(rid,i)->int`, `col_float(rid,i)->float`, `col_str(rid,i)->str|None`, `is_null(rid,i)->int`, `error()->str`. Symbols registered: `__sql_open, __sql_prepare, __sql_bind_int, __sql_bind_float, __sql_bind_str, __sql_exec, __sql_query, __sql_next, __sql_col_index, __sql_col_int, __sql_col_float, __sql_col_str, __sql_is_null, __sql_error`.

- [ ] **Step 1: Write the failing runtime test**

Create `tests/test_m38.py`:

```python
"""M38: SQLite persistence (Sql.twl)."""


def test_sqlite_runtime_roundtrip():
    from tawla.sqlite_runtime import STATE
    STATE.reset()
    db = STATE.open(":memory:")
    assert db >= 0
    s = STATE.prepare(db, "CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT, age INT)")
    assert STATE.exec(s) == 0
    ins = STATE.prepare(db, "INSERT INTO users(name, age) VALUES (?, ?)")
    STATE.bind_str(ins, 0, "Ada")
    STATE.bind_int(ins, 1, 36)
    assert STATE.exec(ins) == 0
    q = STATE.prepare(db, "SELECT id, name, age FROM users WHERE age > ?")
    STATE.bind_int(q, 0, 18)
    r = STATE.query(q)
    assert r >= 0
    assert STATE.next(r) == 1
    assert STATE.col_index(r, "name") == 1
    assert STATE.col_str(r, 1) == "Ada"
    assert STATE.col_int(r, 2) == 36
    assert STATE.is_null(r, 1) == 0
    assert STATE.next(r) == 0
    # error path: bad SQL -> status 1, message stashed
    bad = STATE.prepare(db, "NOT VALID SQL")
    assert STATE.exec(bad) == 1
    assert STATE.error() != ""
    STATE.reset()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_m38.py -v`
Expected: FAIL — `tawla.sqlite_runtime` doesn't exist (ImportError).

- [ ] **Step 3: Create the runtime**

Create `tawla/sqlite_runtime.py`:

```python
"""SQLite for Tawla's Sql.twl, hosted in Python and handed to the JIT via
llvmlite's add_symbol (like fetch_runtime).

Fallible operations return a status code and stash the error message; Sql.twl
checks the status and does `throw __sql_error()`, turning a Python-side failure
into a catchable Tawla exception (the runtime cannot unwind JIT frames itself).
"""

import ctypes
import sqlite3

import llvmlite.binding as llvm

from .gc_runtime import HEAP


class SqlState:
    def __init__(self):
        self.conns = {}
        self.stmts = {}   # sid -> [conn_id, sql, params]
        self.rsets = {}   # rid -> {"data": list, "cols": dict, "pos": int}
        self._next = 1
        self.err = ""

    def reset(self):
        for c in self.conns.values():
            try:
                c.close()
            except Exception:
                pass
        self.conns.clear()
        self.stmts.clear()
        self.rsets.clear()
        self._next = 1
        self.err = ""

    def _id(self):
        i = self._next
        self._next += 1
        return i

    def open(self, path):
        try:
            conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
            cid = self._id()
            self.conns[cid] = conn
            return cid
        except Exception as e:
            self.err = str(e)
            return -1

    def prepare(self, cid, sql):
        sid = self._id()
        self.stmts[sid] = [cid, sql, []]
        return sid

    def _bind(self, sid, index, value):
        params = self.stmts[sid][2]
        while len(params) <= index:
            params.append(None)
        params[index] = value

    def bind_int(self, sid, index, value):
        self._bind(sid, index, value)

    def bind_float(self, sid, index, value):
        self._bind(sid, index, value)

    def bind_str(self, sid, index, value):
        self._bind(sid, index, value)

    def exec(self, sid):
        cid, sql, params = self.stmts[sid]
        try:
            self.conns[cid].execute(sql, params)
            return 0
        except Exception as e:
            self.err = str(e)
            return 1

    def query(self, sid):
        cid, sql, params = self.stmts[sid]
        try:
            cur = self.conns[cid].execute(sql, params)
            data = cur.fetchall()
            cols = {d[0]: idx for idx, d in enumerate(cur.description or [])}
            rid = self._id()
            self.rsets[rid] = {"data": data, "cols": cols, "pos": -1}
            return rid
        except Exception as e:
            self.err = str(e)
            return -1

    def next(self, rid):
        rs = self.rsets[rid]
        rs["pos"] += 1
        return 1 if rs["pos"] < len(rs["data"]) else 0

    def _cell(self, rid, i):
        rs = self.rsets[rid]
        return rs["data"][rs["pos"]][i]

    def col_index(self, rid, name):
        return self.rsets[rid]["cols"].get(name, -1)

    def col_int(self, rid, i):
        v = self._cell(rid, i)
        if v is None:
            return 0
        try:
            return int(v)
        except (ValueError, TypeError):
            return 0

    def col_float(self, rid, i):
        v = self._cell(rid, i)
        if v is None:
            return 0.0
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.0

    def col_str(self, rid, i):
        v = self._cell(rid, i)
        return None if v is None else str(v)

    def is_null(self, rid, i):
        return 1 if self._cell(rid, i) is None else 0

    def error(self):
        return self.err


STATE = SqlState()


def _alloc(s):
    data = s.encode("utf-8") + b"\x00"
    addr = HEAP.alloc(len(data))
    ctypes.memmove(addr, data, len(data))
    return addr


def _alloc_or_null(s):
    return _alloc(s) if s is not None else 0


def _dec(b):
    return b.decode("utf-8") if b else ""


_c_open = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_char_p)(lambda p: STATE.open(_dec(p)))
_c_prepare = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32, ctypes.c_char_p)(
    lambda c, s: STATE.prepare(c, _dec(s))
)
_c_bind_int = ctypes.CFUNCTYPE(None, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32)(
    lambda s, i, v: STATE.bind_int(s, i, v)
)
_c_bind_float = ctypes.CFUNCTYPE(None, ctypes.c_int32, ctypes.c_int32, ctypes.c_double)(
    lambda s, i, v: STATE.bind_float(s, i, v)
)
_c_bind_str = ctypes.CFUNCTYPE(None, ctypes.c_int32, ctypes.c_int32, ctypes.c_char_p)(
    lambda s, i, v: STATE.bind_str(s, i, _dec(v))
)
_c_exec = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32)(lambda s: STATE.exec(s))
_c_query = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32)(lambda s: STATE.query(s))
_c_next = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32)(lambda r: STATE.next(r))
_c_col_index = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32, ctypes.c_char_p)(
    lambda r, n: STATE.col_index(r, _dec(n))
)
_c_col_int = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32, ctypes.c_int32)(
    lambda r, i: STATE.col_int(r, i)
)
_c_col_float = ctypes.CFUNCTYPE(ctypes.c_double, ctypes.c_int32, ctypes.c_int32)(
    lambda r, i: STATE.col_float(r, i)
)
_c_col_str = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32)(
    lambda r, i: _alloc_or_null(STATE.col_str(r, i))
)
_c_is_null = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32, ctypes.c_int32)(
    lambda r, i: STATE.is_null(r, i)
)
_c_error = ctypes.CFUNCTYPE(ctypes.c_void_p)(lambda: _alloc(STATE.error()))

_CALLBACKS = [
    _c_open, _c_prepare, _c_bind_int, _c_bind_float, _c_bind_str, _c_exec, _c_query,
    _c_next, _c_col_index, _c_col_int, _c_col_float, _c_col_str, _c_is_null, _c_error,
]
_registered = False


def install():
    """Register the SQLite primitives with llvmlite, then clear state for a run."""
    global _registered
    if not _registered:
        cast = ctypes.cast
        llvm.add_symbol("__sql_open", cast(_c_open, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_prepare", cast(_c_prepare, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_bind_int", cast(_c_bind_int, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_bind_float", cast(_c_bind_float, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_bind_str", cast(_c_bind_str, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_exec", cast(_c_exec, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_query", cast(_c_query, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_next", cast(_c_next, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_col_index", cast(_c_col_index, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_col_int", cast(_c_col_int, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_col_float", cast(_c_col_float, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_col_str", cast(_c_col_str, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_is_null", cast(_c_is_null, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_error", cast(_c_error, ctypes.c_void_p).value)
        _registered = True
    STATE.reset()
```

- [ ] **Step 4: Run the runtime test**

Run: `venv/Scripts/python.exe -m pytest tests/test_m38.py -v`
Expected: PASS.

- [ ] **Step 5: Wire into the compiler**

In `tawla/compiler.py`, add `sqlite_runtime` to the runtime import line:

```python
from . import eh_runtime, fetch_runtime, gc_runtime, http_runtime, io_runtime, sqlite_runtime, str_runtime
```

and call its install in `run_file`, after `fetch_runtime.install()`:

```python
    fetch_runtime.install()
    sqlite_runtime.install()
```

- [ ] **Step 6: Commit**

```bash
git add tawla/sqlite_runtime.py tawla/compiler.py tests/test_m38.py
git commit -m "sqlite_runtime: SqlState + ctypes wrappers; wire into compiler"
```

---

## Task 2: Wire the 14 `__sql_*` builtins (sema + codegen)

**Files:** Modify `tawla/sema.py`, `tawla/codegen.py`; test `tests/test_m38.py`.

**Interfaces — Consumes:** the `__sql_*` symbols registered in Task 1. **Produces:** the 14 builtins callable from Tawla with the signatures in the spec's builtins table.

- [ ] **Step 1: Write the failing end-to-end test**

Append to `tests/test_m38.py`:

```python
def test_sql_builtins_end_to_end(run_twl):
    src = (
        "class Main { void main() {"
        ' int db = __sql_open(":memory:");'
        ' int c = __sql_prepare(db, "CREATE TABLE t(x INT)");'
        " print(__sql_exec(c));"
        ' int ins = __sql_prepare(db, "INSERT INTO t(x) VALUES (?)");'
        " __sql_bind_int(ins, 0, 7); print(__sql_exec(ins));"
        ' int q = __sql_prepare(db, "SELECT x FROM t");'
        " int r = __sql_query(q); print(__sql_next(r)); print(__sql_col_int(r, 0));"
        " } }"
    )
    assert run_twl(src).stdout == "0\n0\n1\n7\n"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_m38.py::test_sql_builtins_end_to_end -v`
Expected: FAIL — sema rejects the unknown `__sql_*` builtins.

- [ ] **Step 3: Declare the builtins in sema**

In `tawla/sema.py` `_BUILTINS`, after the `__http_*` entries, add:

```python
    "__sql_open": ([STRING], INT),
    "__sql_prepare": ([INT, STRING], INT),
    "__sql_bind_int": ([INT, INT, INT], VOID),
    "__sql_bind_float": ([INT, INT, FLOAT], VOID),
    "__sql_bind_str": ([INT, INT, STRING], VOID),
    "__sql_exec": ([INT], INT),
    "__sql_query": ([INT], INT),
    "__sql_next": ([INT], INT),
    "__sql_col_index": ([INT, STRING], INT),
    "__sql_col_int": ([INT, INT], INT),
    "__sql_col_float": ([INT, INT], FLOAT),
    "__sql_col_str": ([INT, INT], STRING),
    "__sql_is_null": ([INT, INT], INT),
    "__sql_error": ([], STRING),
```

- [ ] **Step 4: Declare the functions in codegen**

In `tawla/codegen.py`, where the other runtime externs are declared (near `self.http_query`), add:

```python
        self.sql_open = ir.Function(self.module, ir.FunctionType(i32, [i8ptr]), name="__sql_open")
        self.sql_prepare = ir.Function(self.module, ir.FunctionType(i32, [i32, i8ptr]), name="__sql_prepare")
        self.sql_bind_int = ir.Function(self.module, ir.FunctionType(void, [i32, i32, i32]), name="__sql_bind_int")
        self.sql_bind_float = ir.Function(self.module, ir.FunctionType(void, [i32, i32, f64]), name="__sql_bind_float")
        self.sql_bind_str = ir.Function(self.module, ir.FunctionType(void, [i32, i32, i8ptr]), name="__sql_bind_str")
        self.sql_exec = ir.Function(self.module, ir.FunctionType(i32, [i32]), name="__sql_exec")
        self.sql_query = ir.Function(self.module, ir.FunctionType(i32, [i32]), name="__sql_query")
        self.sql_next = ir.Function(self.module, ir.FunctionType(i32, [i32]), name="__sql_next")
        self.sql_col_index = ir.Function(self.module, ir.FunctionType(i32, [i32, i8ptr]), name="__sql_col_index")
        self.sql_col_int = ir.Function(self.module, ir.FunctionType(i32, [i32, i32]), name="__sql_col_int")
        self.sql_col_float = ir.Function(self.module, ir.FunctionType(f64, [i32, i32]), name="__sql_col_float")
        self.sql_col_str = ir.Function(self.module, ir.FunctionType(i8ptr, [i32, i32]), name="__sql_col_str")
        self.sql_is_null = ir.Function(self.module, ir.FunctionType(i32, [i32, i32]), name="__sql_is_null")
        self.sql_error = ir.Function(self.module, ir.FunctionType(i8ptr, []), name="__sql_error")
```

- [ ] **Step 5: Dispatch the builtins**

In `tawla/codegen.py`, in the `_gen_builtin_call` dispatch chain (after the `__http_*` cases), add:

```python
        if name == "__sql_open":
            return self.builder.call(self.sql_open, [self._gen_expr(args[0])])
        if name == "__sql_prepare":
            return self.builder.call(self.sql_prepare, [self._gen_expr(args[0]), self._gen_expr(args[1])])
        if name == "__sql_bind_int":
            return self.builder.call(self.sql_bind_int, [self._gen_expr(args[0]), self._gen_expr(args[1]), self._gen_expr(args[2])])
        if name == "__sql_bind_float":
            return self.builder.call(self.sql_bind_float, [self._gen_expr(args[0]), self._gen_expr(args[1]), self._as_f64(args[2])])
        if name == "__sql_bind_str":
            return self.builder.call(self.sql_bind_str, [self._gen_expr(args[0]), self._gen_expr(args[1]), self._gen_expr(args[2])])
        if name == "__sql_exec":
            return self.builder.call(self.sql_exec, [self._gen_expr(args[0])])
        if name == "__sql_query":
            return self.builder.call(self.sql_query, [self._gen_expr(args[0])])
        if name == "__sql_next":
            return self.builder.call(self.sql_next, [self._gen_expr(args[0])])
        if name == "__sql_col_index":
            return self.builder.call(self.sql_col_index, [self._gen_expr(args[0]), self._gen_expr(args[1])])
        if name == "__sql_col_int":
            return self.builder.call(self.sql_col_int, [self._gen_expr(args[0]), self._gen_expr(args[1])])
        if name == "__sql_col_float":
            return self.builder.call(self.sql_col_float, [self._gen_expr(args[0]), self._gen_expr(args[1])])
        if name == "__sql_col_str":
            return self.builder.call(self.sql_col_str, [self._gen_expr(args[0]), self._gen_expr(args[1])])
        if name == "__sql_is_null":
            return self.builder.call(self.sql_is_null, [self._gen_expr(args[0]), self._gen_expr(args[1])])
        if name == "__sql_error":
            return self.builder.call(self.sql_error, [])
```

- [ ] **Step 6: Run the end-to-end test**

Run: `venv/Scripts/python.exe -m pytest tests/test_m38.py -v`
Expected: PASS (both tests).

- [ ] **Step 7: Commit**

```bash
git add tawla/sema.py tawla/codegen.py tests/test_m38.py
git commit -m "Wire __sql_* builtins (sema + codegen)"
```

---

## Task 3: `Sql.twl` — Db / Stmt / Rows + full tests

**Files:** Create `tawla/stdlib/Sql.twl`; test `tests/test_m38.py`.

**Interfaces — Consumes:** the 14 `__sql_*` builtins from Task 2. **Produces:** the `Db`/`Stmt`/`Rows` classes per the spec.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_m38.py`:

```python
def _main(body):
    return 'import "Sql.twl"; class Main { void main() { ' + body + " } }"


def test_sql_insert_and_query(run_twl):
    body = (
        'Db db = new Db(":memory:");'
        ' db.exec("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT, age INT)");'
        ' Stmt ins = db.prepare("INSERT INTO users(name, age) VALUES (?, ?)");'
        ' ins.bindString(0, "Ada"); ins.bindInt(1, 36); ins.exec();'
        ' Stmt q = db.prepare("SELECT id, name, age FROM users WHERE age > ?");'
        " q.bindInt(0, 18); Rows r = q.query();"
        ' while (r.next()) { print(r.getString("name")); print(r.getIntAt(2)); }'
    )
    assert run_twl(_main(body)).stdout == "Ada\n36\n"


def test_sql_multiple_rows(run_twl):
    body = (
        'Db db = new Db(":memory:"); db.exec("CREATE TABLE t(x INT)");'
        ' Stmt ins = db.prepare("INSERT INTO t(x) VALUES (?)");'
        " ins.bindInt(0, 1); ins.exec();"
        ' Stmt ins2 = db.prepare("INSERT INTO t(x) VALUES (?)");'
        " ins2.bindInt(0, 2); ins2.exec();"
        ' Rows r = db.prepare("SELECT x FROM t ORDER BY x").query();'
        " int sum = 0; while (r.next()) { sum = sum + r.getInt(\"x\"); } print(sum);"
    )
    assert run_twl(_main(body)).stdout == "3\n"


def test_sql_float_roundtrip(run_twl):
    body = (
        'Db db = new Db(":memory:"); db.exec("CREATE TABLE m(v REAL)");'
        ' Stmt ins = db.prepare("INSERT INTO m(v) VALUES (?)");'
        " ins.bindFloat(0, 2.5); ins.exec();"
        ' Rows r = db.prepare("SELECT v FROM m").query();'
        ' r.next(); print(r.getFloat("v"));'
    )
    assert run_twl(_main(body)).stdout == "2.5\n"


def test_sql_null_handling(run_twl):
    body = (
        'Db db = new Db(":memory:"); db.exec("CREATE TABLE t(name TEXT)");'
        ' db.exec("INSERT INTO t(name) VALUES (NULL)");'
        ' Rows r = db.prepare("SELECT name FROM t").query(); r.next();'
        ' if (r.isNull("name")) { print("null"); } else { print(r.getString("name")); }'
    )
    assert run_twl(_main(body)).stdout == "null\n"


def test_sql_error_is_catchable(run_twl):
    body = (
        'Db db = new Db(":memory:");'
        ' fuck_around { db.exec("NOT VALID SQL"); print("ran"); }'
        ' find_out (e) { print("caught"); }'
    )
    assert run_twl(_main(body)).stdout == "caught\n"


def test_sql_uncaught_error_exits_nonzero(run_twl):
    body = 'Db db = new Db(":memory:"); db.exec("NOT VALID SQL");'
    r = run_twl(_main(body))
    assert r.returncode != 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_m38.py -k "insert or rows or float or null or error" -v`
Expected: FAIL — `Sql.twl` does not exist, so the import fails.

- [ ] **Step 3: Create `Sql.twl`**

Create `tawla/stdlib/Sql.twl`:

```tawla
// SQLite database access. Import with:  import "Sql.twl";
//
// Db opens a database, Stmt is a prepared statement you bind parameters onto,
// and Rows is a cursor over a query result. SQL errors are thrown — catch them
// with  fuck_around { ... } find_out (e) { ... }.

class Rows {
    private int id;
    public Rows(int id) { this.id = id; }

    public bool next() { return __sql_next(this.id) != 0; }

    public int getIntAt(int i) { return __sql_col_int(this.id, i); }
    public float getFloatAt(int i) { return __sql_col_float(this.id, i); }
    public string getStringAt(int i) { return __sql_col_str(this.id, i); }
    public bool isNullAt(int i) { return __sql_is_null(this.id, i) != 0; }

    public int getInt(string name) { return __sql_col_int(this.id, __sql_col_index(this.id, name)); }
    public float getFloat(string name) { return __sql_col_float(this.id, __sql_col_index(this.id, name)); }
    public string getString(string name) { return __sql_col_str(this.id, __sql_col_index(this.id, name)); }
    public bool isNull(string name) { return __sql_is_null(this.id, __sql_col_index(this.id, name)) != 0; }
}

class Stmt {
    private int id;
    public Stmt(int id) { this.id = id; }

    public void bindInt(int index, int value) { __sql_bind_int(this.id, index, value); }
    public void bindFloat(int index, float value) { __sql_bind_float(this.id, index, value); }
    public void bindString(int index, string value) { __sql_bind_str(this.id, index, value); }

    public void exec() {
        if (__sql_exec(this.id) != 0) { throw __sql_error(); }
    }

    public Rows query() {
        int r = __sql_query(this.id);
        if (r < 0) { throw __sql_error(); }
        return new Rows(r);
    }
}

class Db {
    private int id;
    public Db(string path) {
        this.id = __sql_open(path);
        if (this.id < 0) { throw __sql_error(); }
    }

    public Stmt prepare(string sql) { return new Stmt(__sql_prepare(this.id, sql)); }

    public void exec(string sql) {
        Stmt s = this.prepare(sql);
        s.exec();
    }
}
```

- [ ] **Step 4: Run the Sql.twl tests**

Run: `venv/Scripts/python.exe -m pytest tests/test_m38.py -v`
Expected: PASS (all M38 tests).

- [ ] **Step 5: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all pass, no regressions.

- [ ] **Step 6: Commit**

```bash
git add tawla/stdlib/Sql.twl tests/test_m38.py
git commit -m "Add Sql.twl (Db/Stmt/Rows) over the sqlite builtins"
```

---

## Task 4: Example, docs, spec hiddenimport, version, verification

**Files:** Create `examples/sql_demo.twl`; modify `tawlac.spec`, `README.md`, `tawla_lang_docs/index.html`, `pyproject.toml`, `tawla/__init__.py`.

- [ ] **Step 1: Create the example**

Create `examples/sql_demo.twl`:

```tawla
// SQLite: prepared statements, parameter binding, a row cursor, and catchable
// SQL errors. Uses an in-memory database, so it leaves no file behind.
import "Sql.twl";

class Main {
    void main() {
        Db db = new Db(":memory:");
        db.exec("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT, age INT)");

        Stmt ins = db.prepare("INSERT INTO users(name, age) VALUES (?, ?)");
        ins.bindString(0, "Ada"); ins.bindInt(1, 36); ins.exec();

        Stmt ins2 = db.prepare("INSERT INTO users(name, age) VALUES (?, ?)");
        ins2.bindString(0, "Linus"); ins2.bindInt(1, 54); ins2.exec();

        Stmt q = db.prepare("SELECT name, age FROM users WHERE age > ? ORDER BY age");
        q.bindInt(0, 40);
        Rows r = q.query();
        while (r.next()) {
            print(r.getString("name") + " is " + toString(r.getInt("age")));
        }

        // SQL errors are catchable
        fuck_around {
            db.exec("INSERT INTO nope VALUES (1)");
        } find_out (e) {
            print("db error handled");
        }
    }
}
```

- [ ] **Step 2: Verify the example runs**

Run: `venv/Scripts/python.exe -m tawla run examples/sql_demo.twl`
Expected output:
```
Linus is 54
db error handled
```

- [ ] **Step 3: Add the runtime to the PyInstaller spec**

In `tawlac.spec`, add `"tawla.sqlite_runtime"` to the `hiddenimports += [...]` list.

- [ ] **Step 4: Update the README**

In `README.md`, add a bullet in the "What the language can do" list, after the HTTP-client (`fetch`) bullet:

```markdown
- **SQLite:** `import "Sql.twl";` gives you `Db`, prepared `Stmt`s, and a `Rows`
  cursor — `Db db = new Db("app.db"); Stmt q = db.prepare("SELECT name FROM users WHERE age > ?"); q.bindInt(0, 18); Rows r = q.query();` then `r.next()` / `r.getString("name")`.
  Parameters bind by index (injection-safe); SQL errors throw (catch with
  `fuck_around`/`find_out`).
```

- [ ] **Step 5: Update the docs site**

In `tawla_lang_docs/index.html`, add a `#sql` section after the `#fetch` section
(and a sidebar link `<a href="#sql">SQLite</a>` in the Standard library nav
group), with a short intro and this example (escape `<`/`>`/`&` as other code
blocks do):

```html
    <section id="sql">
      <h2>SQLite</h2>
      <p><code>import "Sql.twl";</code> gives you an embedded SQL database. Open a <code>Db</code>, run statements, and read query results through a <code>Rows</code> cursor. Parameters bind by index with <code>?</code> placeholders (so there's no SQL injection), and SQL errors are thrown — catch them with <code>fuck_around</code> / <code>find_out</code>.</p>
      <div class="code">
        <div class="code-head"><span class="dot"></span><span class="fname">db.twl</span><button class="copy-btn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg><span class="copy-label">Copy</span></button></div>
        <pre><code class="twl">Db db = new Db("app.db");
db.exec("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT, age INT)");

Stmt ins = db.prepare("INSERT INTO users(name, age) VALUES (?, ?)");
ins.bindString(0, "Ada"); ins.bindInt(1, 36); ins.exec();

Stmt q = db.prepare("SELECT name FROM users WHERE age > ?");
q.bindInt(0, 18);
Rows r = q.query();
while (r.next()) { print(r.getString("name")); }</code></pre>
      </div>
    </section>
```

- [ ] **Step 6: Bump the version to 1.7.0**

`pyproject.toml` line 3 → `version = "1.7.0"`; `tawla/__init__.py` line 3 →
`__version__ = "1.7.0"`.

- [ ] **Step 7: Run the full suite + version + frozen smoke**

Run: `venv/Scripts/python.exe -m pytest -q` → all pass.
Run: `venv/Scripts/python.exe -m tawla version` → `tawlac 1.7.0`.
Rebuild the binary and confirm SQLite works frozen:
```bash
venv/Scripts/pyinstaller.exe tawlac.spec --clean --noconfirm
./dist/tawlac.exe run examples/sql_demo.twl
```
Expected: `Linus is 54` / `db error handled`.

- [ ] **Step 8: Commit (compiler) + push docs (separate repo)**

```bash
git add examples/sql_demo.twl tawlac.spec README.md pyproject.toml tawla/__init__.py
git commit -m "Add SQLite example, docs, hiddenimport; bump to 1.7.0"
```

```bash
cd D:\Projects\tawla_lang_docs
git add index.html
git commit -m "Document SQLite (Sql.twl)"
git push
cd D:\Projects\Tawla_lang
```

---

## Done criteria

- `Db`/`Stmt`/`Rows` work: create/insert via prepared statements with typed
  binds, query, iterate rows, read columns by name and index, NULL handled.
- SQL errors throw and are catchable; uncaught errors exit non-zero.
- `tests/test_m38.py` + full suite green; `tawlac version` → `1.7.0`;
  the frozen binary runs `sql_demo.twl`.

## Release (on the user's go-ahead)

Merge to `main`, push, `git tag v1.7.0 && git push origin v1.7.0` (builds
binaries), then build + publish 1.7.0 to PyPI.
