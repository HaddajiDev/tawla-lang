# Backend Essentials (`Sys.twl` / `Fs.twl` / `Crypto.twl`) — Design

## Goal

Add the small primitives every backend needs and Tawla lacks: environment
variables, wall-clock time + sleep, UUIDs, file I/O, and hashing/HMAC. Shipped
as three themed standard-library modules over one new runtime, in a single
release.

## Tawla API

### `Sys.twl` — `import "Sys.twl";`

- `string getenv(string name)` — environment variable value, or `null` if unset.
- `int now()` — current time as epoch **seconds**.
- `float nowMillis()` — current time as epoch **milliseconds**.
- `void sleepMillis(int ms)` — pause execution for `ms` milliseconds.
- `string uuid()` — a random UUID, dashed v4 form (e.g.
  `"f47ac10b-58cc-4372-a567-0e02b2c3d479"`).

### `Fs.twl` — `import "Fs.twl";`

- `string readFile(string path)` — file contents as a string. **Throws** on
  failure (missing file, permission).
- `void writeFile(string path, string content)` — write (truncating). **Throws**
  on failure.
- `void appendFile(string path, string content)` — append. **Throws** on failure.
- `bool exists(string path)` — whether the path exists. Never throws.

### `Crypto.twl` — `import "Crypto.twl";`

- `string sha256(string s)` — lowercase hex SHA-256 digest of the UTF-8 bytes.
- `string hmacSha256(string key, string message)` — lowercase hex HMAC-SHA-256,
  for signing tokens / sessions / webhooks.

## Key decision: 32-bit int and time

Tawla's `int` is **32-bit** (`i32`). Epoch seconds (~1.75e9) fit until
2038-01-19, so `now()` returns `int` — with that documented caveat. Epoch
milliseconds (~1.75e12) overflow a 32-bit int, so **`nowMillis()` returns
`float`** (an f64 represents integer milliseconds exactly up to 2^53).
`sleepMillis` takes an `int` (millisecond delays are small).

## Mechanism — `tawla/sys_runtime.py`

One Python-hosted runtime (modeled on `fetch_runtime`/`sqlite_runtime`) using
`os`, `time`, `uuid`, `hashlib`, and `hmac`. Registered with the JIT via
`llvm.add_symbol` and reset per run. Strings are returned through the GC
`_alloc` helper; returning `0` yields a null `char*` (Tawla `null`).

File errors follow the SQLite pattern — a Python-side failure cannot unwind JIT
frames, so the fallible file ops return a sentinel and stash the message, and
the `Fs.twl` wrapper turns that into a catchable Tawla `throw`:

- `__file_read(path) -> char*` — file contents, or **null** on error (message
  stashed). (An empty file returns `""`, distinct from `null`.)
- `__file_write(path, content) -> int` — `0` ok, `1` on error (message stashed).
- `__file_append(path, content) -> int` — `0` ok, `1` on error.
- `__fs_error() -> char*` — the last stashed file error message.

`getenv` returns `null` for an absent variable (that is not an error). Other
builtins are total.

### Builtins (wired in sema + codegen, like `__sql_*`)

| Builtin | Signature |
|---------|-----------|
| `__env_get` | `(string) -> string` |
| `__time_secs` | `() -> int` |
| `__time_millis` | `() -> float` |
| `__sleep_millis` | `(int) -> void` |
| `__uuid` | `() -> string` |
| `__file_read` | `(string) -> string` |
| `__file_write` | `(string, string) -> int` |
| `__file_append` | `(string, string) -> int` |
| `__file_exists` | `(string) -> int` |
| `__fs_error` | `() -> string` |
| `__sha256` | `(string) -> string` |
| `__hmac_sha256` | `(string, string) -> string` |

Runtime behavior:
- `__env_get`: `os.environ.get(name)` → string or null.
- `__time_secs`: `int(time.time())`.
- `__time_millis`: `float(time.time() * 1000.0)`.
- `__sleep_millis`: `time.sleep(ms / 1000.0)`.
- `__uuid`: `str(uuid.uuid4())`.
- `__file_read`: read text (UTF-8); on `OSError` stash `str(e)`, return null.
- `__file_write` / `__file_append`: write/append text; `0`/`1` + stash on error.
- `__file_exists`: `1 if os.path.exists(path) else 0`.
- `__sha256`: `hashlib.sha256(s.encode()).hexdigest()`.
- `__hmac_sha256`: `hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()`.

### `Sys.twl` / `Fs.twl` / `Crypto.twl` wrappers

Ordinary Tawla free functions forwarding to the builtins (like `IO.twl`):

```tawla
// Fs.twl
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

`Sys.twl` and `Crypto.twl` are direct one-line forwards (no error handling).

## Components / files

- `tawla/sys_runtime.py` — new runtime (env/time/uuid/file/hash + install).
- `tawla/compiler.py` — register `sys_runtime.install()`.
- `tawla/sema.py` — declare the 12 builtins.
- `tawla/codegen.py` — declare + dispatch the 12 builtins.
- `tawla/stdlib/Sys.twl`, `tawla/stdlib/Fs.twl`, `tawla/stdlib/Crypto.twl`.
- `tawlac.spec` — add `tawla.sys_runtime` to `hiddenimports`.
- `tests/test_m39.py`; `examples/essentials.twl`; README + docs; version → 1.8.0.

## Testing (`tests/test_m39.py`)

- env: set an env var in the subprocess, `getenv` returns it; an unset var → `null`.
- time: `now()` is a plausibly large int (> 1_700_000_000); `nowMillis()` is a
  float `>= now() * 1000` (roughly); `sleepMillis(50)` returns without error.
- uuid: `uuid()` returns a 36-char string containing `-`; two calls differ.
- file I/O: `writeFile` then `readFile` round-trips; `appendFile` extends;
  `exists` true after write / false for a missing path (use a tmp path).
- file error throws: `fuck_around { readFile("nope.nonexistent"); } find_out (e) { ... }`
  is caught; uncaught read of a missing file exits non-zero.
- crypto: `sha256("abc")` equals the known digest
  `ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad`;
  `hmacSha256("key", "msg")` is stable / equals Python's value.

## Out of scope

- Directory ops (list/mkdir/glob), `deleteFile`, env mutation (`setenv`).
- Date formatting/parsing, timezones, a monotonic clock.
- Password KDFs (bcrypt/argon2), base64, other digests (md5/sha1).
