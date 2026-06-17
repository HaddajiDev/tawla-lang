# SQLite Persistence (`Sql.twl`) — Design

## Goal

Give Tawla a real database: an embedded SQLite binding exposed as a `Sql.twl`
standard-library module, with prepared statements, parameter binding, a row
cursor, and SQL errors that integrate with Tawla's exception system.

## Tawla API

```tawla
import "Sql.twl";

Db db = new Db("app.db");          // or ":memory:"
db.exec("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT, age INT)");

Stmt ins = db.prepare("INSERT INTO users(name, age) VALUES (?, ?)");
ins.bindString(0, "Ada");
ins.bindInt(1, 36);
ins.exec();

Stmt q = db.prepare("SELECT id, name FROM users WHERE age > ?");
q.bindInt(0, 18);
Rows rows = q.query();
while (rows.next()) {
    print(rows.getInt("id") + ": " + rows.getString("name"));
}
```

### Classes

- **`Db`**
  - `new Db(string path)` — open/create a database file (or `":memory:"`).
    Throws on failure (e.g. unwritable path).
  - `Stmt prepare(string sql)` — create a prepared statement.
  - `void exec(string sql)` — convenience for a param-free statement
    (prepares + execs).

- **`Stmt`**
  - `void bindInt(int index, int value)` — bind a parameter (0-based `?`
    position).
  - `void bindFloat(int index, float value)`
  - `void bindString(int index, string value)`
  - `void exec()` — run a non-SELECT statement. Throws on SQL error.
  - `Rows query()` — run a SELECT and return a cursor. Throws on SQL error.

- **`Rows`** (cursor; positioned before the first row)
  - `bool next()` — advance to the next row; `false` when exhausted.
  - By name: `int getInt(string)`, `float getFloat(string)`,
    `string getString(string)`, `bool isNull(string)`.
  - By index (0-based): `int getIntAt(int)`, `float getFloatAt(int)`,
    `string getStringAt(int)`, `bool isNullAt(int)`.

### Semantics

- **Parameters** use SQLite `?` placeholders, bound by 0-based index with typed
  `bindX`. This is the only way to pass values — no string interpolation into
  SQL — so injection is structurally prevented.
- **NULL cells:** `getString` returns `null`; `getInt`/`getFloat` return `0`;
  `isNull`/`isNullAt` distinguish a real NULL.
- **Type coercion** (SQLite is dynamically typed): `getInt` returns the cell as
  an integer (`int(value)`, `0` for NULL or non-numeric); `getFloat` as a double
  (`0.0` for NULL); `getString` as text (`null` for NULL, otherwise `str(value)`).
- **Autocommit:** the connection opens with `isolation_level=None`, so each
  statement commits immediately and explicit `BEGIN`/`COMMIT` (issued via
  `db.exec`) also work for multi-statement transactions.
- **Errors throw.** A failed `Db(...)`, `Stmt.exec()`, or `Stmt.query()` raises a
  Tawla exception carrying the SQLite error message, catchable with
  `fuck_around { ... } find_out (e) { ... }`. Uncaught, it prints and exits like
  any other error.

## Mechanism — `tawla/sqlite_runtime.py`

Modeled on `fetch_runtime`/`http_runtime`: a `SqlState` (instance `STATE`) holds
connections, statements, and result sets keyed by integer ids; functions are
registered with the JIT via `llvm.add_symbol`; strings are returned through the
GC `_alloc_str` helper (returning `0` for a null `char*`).

Because a Python-side exception cannot unwind JIT frames, **fallible operations
return a status code and stash the error message**; the `Sql.twl` wrapper checks
the status and calls `throw __sql_error()` — turning the failure into a catchable
Tawla exception via the existing `throw`/`_raise`/`longjmp` path.

`SqlState` (using Python `sqlite3`, `connect(path, isolation_level=None,
check_same_thread=False)`):
- `open(path) -> int` — connection id, or `-1` + stored error.
- `prepare(db_id, sql) -> int` — statement id; stores `(db_id, sql, params=[])`.
  Never fails (real preparation is deferred to exec/query, where SQL errors
  surface).
- `bind_int(sid, i, v)` / `bind_float(sid, i, v)` / `bind_str(sid, i, v)` — set
  `params[i]` (growing the list as needed).
- `exec(sid) -> int` — `conn.execute(sql, params)`; returns `0`, or `1` + stored
  error.
- `query(sid) -> int` — `cur = conn.execute(sql, params)`; materialize
  `cur.fetchall()` + a column-name→index map into a result set; return its id, or
  `-1` + stored error. Cursor starts before row 0.
- `next(rows_id) -> int` — advance; `1` if now on a valid row, else `0`.
- `col_index(rows_id, name) -> int` — column index for `name`, or `-1`.
- `col_int(rows_id, i) -> int`, `col_float(rows_id, i) -> float`,
  `col_str(rows_id, i) -> <char*|null>` — current-row cell by index, with the
  coercion/NULL rules above.
- `is_null(rows_id, i) -> int` — `1` if the cell is NULL.
- `error() -> <char*>` — the last stored error message.

### Builtins (wired in sema + codegen, like `__http_*`)

| Builtin | Signature |
|---------|-----------|
| `__sql_open` | `(string) -> int` |
| `__sql_prepare` | `(int, string) -> int` |
| `__sql_bind_int` | `(int, int, int) -> void` |
| `__sql_bind_float` | `(int, int, float) -> void` |
| `__sql_bind_str` | `(int, int, string) -> void` |
| `__sql_exec` | `(int) -> int` |
| `__sql_query` | `(int) -> int` |
| `__sql_next` | `(int) -> int` |
| `__sql_col_index` | `(int, string) -> int` |
| `__sql_col_int` | `(int, int) -> int` |
| `__sql_col_float` | `(int, int) -> float` |
| `__sql_col_str` | `(int, int) -> string` |
| `__sql_is_null` | `(int, int) -> int` |
| `__sql_error` | `() -> string` |

The float-typed builtins follow the existing math-builtin pattern (`f64`). The
by-name `Rows` getters call `__sql_col_index` then the matching by-index getter,
so the runtime only implements by-index access.

## Components / files

- `tawla/sqlite_runtime.py` — new runtime (SqlState + ctypes wrappers + install).
- `tawla/compiler.py` — register `sqlite_runtime.install()` alongside the others.
- `tawla/sema.py` — declare the 14 `__sql_*` builtins in `_BUILTINS`.
- `tawla/codegen.py` — declare the 14 functions + dispatch them.
- `tawla/stdlib/Sql.twl` — `Db`, `Stmt`, `Rows`.
- `tawlac.spec` — add `tawla.sqlite_runtime` to `hiddenimports`.
- `tests/test_m38.py`; `examples/sql_demo.twl`; README + docs; version → 1.7.0.

## Testing (`tests/test_m38.py`)

Use `":memory:"` (or a tmp-file db) so tests are isolated:

- create table + insert via prepared statement + bound params, then query and
  read back the row (`getInt`/`getString` by name and by index).
- multiple rows: insert several, iterate with `next()`, count/collect.
- float round-trip: `bindFloat` + `getFloat`.
- NULL: a row with a NULL column → `isNull` true, `getString` null, `getInt` 0.
- `db.exec(sql)` convenience runs a param-free statement.
- error throws: `fuck_around { db.exec("NOT SQL"); } find_out (e) { ... }` is
  caught; a uniqueness/constraint violation is caught.
- uncaught error exits non-zero with the message (regression with the exception
  system).

## Out of scope

- An ORM / query builder / migrations.
- A dedicated transactions API (use raw `BEGIN`/`COMMIT` via `db.exec`).
- Connection pooling and sharing a connection across threads (revisit with
  concurrency).
- Non-SQLite drivers (Postgres/MySQL).
- `bindNull` / binding arbitrary blobs (BLOB columns).
