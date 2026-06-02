# Design: HTTP server core + routing

Status: approved (brainstorm) — pending implementation
Date: 2026-06-02
Milestone: M30 — additive, ships as **1.3.0**

## Goal

Let Tawla programs serve HTTP: a blocking, single-threaded `Server` you drive
from your own loop, a `Request` (method / path / body / respond), and an
Express-style `Router` so route handling reads cleanly. Native socket work is
hosted in Python (like `io_runtime`/`gc_runtime`); the user-facing API is a
bundled `Http.twl` stdlib module.

## Surface (what programs write)

```tawla
import "Http.twl";

class Health : Handler {
    public void handle(Request req) { req.respond(200, "ok"); }
}
class CreateUser : Handler {
    public void handle(Request req) { req.respond(201, req.body()); }
}

class Main {
    void main() {
        Router router = new Router();
        router.get("/health", new Health());
        router.post("/users", new CreateUser());
        new Server(8080).serve(router);     // listens + dispatches forever
    }
}
```

The raw primitives stay public for manual loops:
```tawla
Server s = new Server(8080);
while (true) {
    Request r = s.accept();
    r.respond(200, r.path());
}
```

### API (`Http.twl`)

- `interface Handler { void handle(Request req); }`
- `class Server`:
  - `Server(int port)` — start listening (`port` 0 = OS-assigned).
  - `int port()` — the actual bound port.
  - `Request accept()` — block until the next request.
  - `void serve(Router r)` — `while (true) { r.handle(this.accept()); }`.
- `class Request`:
  - `string method()` / `string path()` / `string body()`
  - `void respond(int status, string body)` — `text/plain`, then closes.
- `class Route { public string method; public string path; public Handler handler; ... }`
- `class Router`:
  - `void get(string path, Handler h)` / `void post(string path, Handler h)`
  - `void handle(Request req)` — first route whose `method`+`path` match (exact)
    gets `handler.handle(req)`; otherwise `req.respond(404, "not found")`.
  - stores routes in a `List<Route>` (object pointers — no interface arrays).

## Native primitives (`tawla/http_runtime.py`)

Python module registered with `llvm.add_symbol`, mirroring `io_runtime`. Holds
two dicts: `servers` (id → listening socket) and `requests` (id → {conn, method,
path, body}); ids are incrementing ints. Reset on `install()`.

- `__http_listen(port: i32) -> i32` — `socket(AF_INET, SOCK_STREAM)`,
  `SO_REUSEADDR`, `bind(("127.0.0.1", port))`, `listen(16)`; store, return id.
- `__http_port(server: i32) -> i32` — `sock.getsockname()[1]`.
- `__http_accept(server: i32) -> i32` — `conn, _ = sock.accept()`; read until
  `b"\r\n\r\n"`; parse the request line (`METHOD PATH HTTP/1.1`) and headers; if
  `Content-Length` is present, keep reading until the body is complete; store
  `{conn, method, path, body}`, return a request id.
- `__http_method/path/body(req: i32) -> i8*` — UTF-8 bytes copied into a
  GC-heap block (`HEAP.alloc` + `ctypes.memmove`, exactly like
  `io_runtime._read_line`); return the address.
- `__http_respond(req: i32, status: i32, body: i8*)` — build
  `f"HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain\r\nContent-Length:
  {n}\r\nConnection: close\r\n\r\n".encode() + body_bytes`, `conn.sendall(...)`,
  `conn.close()`, drop the request. `reason` from a small dict
  (`{200:"OK", 201:"Created", 404:"Not Found", 500:"Internal Server Error"}`,
  default `"OK"`).

CFUNCTYPE signatures: `listen`/`port`/`accept` are `c_int32(args...)`;
`method`/`path`/`body` are `c_void_p(c_int32)`; `respond` is
`None(c_int32, c_int32, c_char_p)`. `install()` registers all six and clears the
dicts.

## Compiler changes

- **sema.py** — add to `_BUILTINS`:
  - `"__http_listen": ([INT], INT)`, `"__http_port": ([INT], INT)`,
    `"__http_accept": ([INT], INT)`, `"__http_method": ([INT], STRING)`,
    `"__http_path": ([INT], STRING)`, `"__http_body": ([INT], STRING)`,
    `"__http_respond": ([INT, INT, STRING], VOID)`.
- **codegen.py** — declare the six externs in `_declare_runtime`
  (`io_read_*`-style) and handle each name in `_gen_builtin` (call the extern;
  string-returning ones return the `i8*` directly; `respond` passes
  `status` i32 and the body `i8*`). `__http_accept` calls `_flush_stdout()`
  before the extern (same as the IO reads), so a `print` issued just before
  blocking — e.g. the bound port — actually reaches stdout instead of sitting in
  the C buffer.
- **compiler.py** — `from . import http_runtime` and call
  `http_runtime.install()` next to `io_runtime.install()`.
- **packaging** — `Http.twl` ships via the existing `stdlib/*.twl` package-data
  rule; the loader's stdlib search path already resolves
  `import "Http.twl"`.

No changes to the language itself — `Http.twl` uses existing features (classes,
interfaces, generics/`List`, `&&`, `void` methods, `while`).

## Testing

`tests/test_m30.py` with a helper that, per test:
1. writes a small server program that binds `port 0`, `print`s `s.port()`
   (flushed by the program's normal output), handles **one** request, and
   returns (so the subprocess exits on its own);
2. starts it with `subprocess.Popen` (cwd = repo root), reads the first stdout
   line to learn the port;
3. sends a real request with `http.client`, returns `(status, body)`;
4. joins the process.

Cases:
- raw `accept` + `respond`: GET `/foo` → echo `req.path()`; assert 200 + `/foo`.
- `req.method()` and `req.body()`: POST with a body, echo it back.
- Router: register `get("/health")` + `post("/users")`; hitting `/health` runs
  that handler (200 "ok"); an unknown path → 404 "not found".
- `port()` returns a non-zero port for `new Server(0)`.
- regression: full suite stays green (the server tests are self-contained
  subprocesses; nothing blocks the suite).

Example: `examples/server.twl` — the Router example from the surface section
(uses a fixed port; documented as run-it-yourself, not run by the suite).

## Limitations (documented)

- Single-threaded, one request at a time.
- Minimal HTTP/1.1: no keep-alive (responses send `Connection: close`), no
  chunked transfer, no TLS.
- Exact path matching only — no `/users/:id` params yet.
- `text/plain` responses until the JSON milestone (which adds `respondJson`).

## Out of scope (later milestones)

- JSON parse/build + `respondJson`.
- Path parameters / query parsing / header access.
- `fetch` (outbound HTTP client).
- Concurrency.
