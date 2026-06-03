# Design: fetch (outbound HTTP client)

Status: approved (brainstorm) — pending implementation
Date: 2026-06-02
Milestone: M34 — additive, ships as **1.3.0** (completes the backend stack)

## Goal

Let Tawla programs make outbound HTTP requests — calling other APIs — mirroring
the inbound server. `fetch(url)` for GET and `httpRequest(method, url, body)`
for everything else, returning a `Response` with a status code and body.

## API (in `Http.twl`)

```tawla
import "Http.twl";

Response r = fetch("http://127.0.0.1:8080/users/1");
if (r.status() == 200) {
    Json data = parseJson(r.body());
    print(data.get("name").asString());
}

Response posted = httpRequest("POST", "http://127.0.0.1:8080/users", "{\"name\":\"ada\"}");
print(posted.status());
```

- `class Response` — holds a native id; `int status()`, `string body()`.
- `Response fetch(string url)` — a GET (free function).
- `Response httpRequest(string method, string url, string body)` — any method;
  `body` is sent only when non-empty.

Network failures (host down, connection refused, timeout, bad URL) → `status()`
returns `0` and `body()` is empty, so a program can check rather than abort.

## Native side (`tawla/fetch_runtime.py`)

Python module hosted via `llvm.add_symbol`, like `http_runtime`/`io_runtime`,
holding a `responses` table (id → {status, body}) reset on `install()`.

- `__fetch(method, url, body) -> int`:
  - Build `urllib.request.Request(url, data=body.encode() if body else None,
    method=method)`. When there's a body, set header
    `Content-Type: application/json` (the common API case).
  - `urllib.request.urlopen(req, timeout=30)`: read status (`resp.status`) and
    body (`resp.read().decode("utf-8", "replace")`).
  - `except urllib.error.HTTPError as e`: capture `e.code` and `e.read()` (the
    error response still has a status + body).
  - `except Exception`: status `0`, body `""` (network failure / bad URL /
    timeout).
  - Store `{status, body}`, return a new id.
- `__fetch_status(id) -> int` — the stored status.
- `__fetch_body(id) -> string` — the stored body, copied to the GC heap
  (`HEAP.alloc` + `memmove`, like `io_runtime`).

CFUNCTYPEs: `__fetch` is `c_int32(c_char_p, c_char_p, c_char_p)`,
`__fetch_status` is `c_int32(c_int32)`, `__fetch_body` is `c_void_p(c_int32)`.

## Compiler wiring

- **sema.py** `_BUILTINS`:
  - `"__fetch": ([STRING, STRING, STRING], INT)`
  - `"__fetch_status": ([INT], INT)`
  - `"__fetch_body": ([INT], STRING)`
- **codegen.py:** declare the three externs in `_declare_runtime`
  (`__fetch` `(i8*,i8*,i8*)->i32`, `__fetch_status` `(i32)->i32`,
  `__fetch_body` `(i32)->i8*`) and handle them in `_gen_builtin` (call the
  extern with the generated args). No `_flush_stdout` needed.
- **compiler.py:** `from . import ... fetch_runtime` and `fetch_runtime.install()`
  alongside the others.
- **Http.twl:** add the `Response` class and the `fetch`/`httpRequest` free
  functions.

## Testing

`tests/test_m34.py`: spin up a tiny Python `http.server` in a background thread
on port 0 (a `BaseHTTPRequestHandler`: GET `/hello` → 200 "world"; GET `/json`
→ 200 `{"name":"ada"}`; POST `/echo` → 200 echoing the request body), read its
chosen port, then run a Tawla program (subprocess, `tawlac run` of a written
file) that uses `fetch`/`httpRequest` against that URL and prints results;
assert on stdout.

- GET: `fetch(".../hello")` → `status()` 200, `body()` "world".
- POST: `httpRequest("POST", ".../echo", "payload")` → body "payload".
- JSON round-trip: `parseJson(fetch(".../json").body()).get("name").asString()`
  → "ada".
- failure: `fetch("http://127.0.0.1:1/")` (refused) → `status()` 0.
- Python-level unit test of `fetch_runtime` is optional; the subprocess tests
  cover the path end to end. Stop the server thread in a `finally`.

Example: `examples/fetch.twl` — documented as run-it-yourself (it needs a
reachable URL), e.g. fetching a localhost endpoint.

## Limitations (documented)

- Blocking, one request at a time (no async).
- No custom request headers beyond the auto `Content-Type: application/json` for
  bodies; no response-header access.
- No redirects beyond urllib's defaults; no TLS client config knobs.

## Out of scope

- This is the last planned backend milestone; nothing queued after it.
