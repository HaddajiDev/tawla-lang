# HTTP Server Core + Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an HTTP `Server`/`Request` with an Express-style `Router`, backed by Python-hosted socket primitives.

**Architecture:** A Python `http_runtime` (raw sockets + minimal HTTP/1.1) exposes `__http_*` primitives via `llvm.add_symbol` (like `io_runtime`); the compiler registers them as builtins; a bundled `Http.twl` wraps them in `Server`/`Request`/`Handler`/`Route`/`Router` classes.

**Tech Stack:** Python 3.11+ (`socket`, `http.client` for tests), llvmlite. Server programs are tested as subprocesses that bind port 0, print the port, handle one request, and exit.

**Reference spec:** `docs/superpowers/specs/2026-06-02-http-server-design.md`

**Milestone:** M30 — additive, ships as **1.3.0** (release is a separate user-triggered step).

---

## File structure

- `tawla/http_runtime.py` — new: Python socket server state + `__http_*` callbacks + `install()`.
- `tawla/sema.py` — `__http_*` builtin signatures.
- `tawla/codegen.py` — `__http_*` externs + `_gen_builtin` branches.
- `tawla/compiler.py` — `http_runtime.install()`.
- `tawla/stdlib/Http.twl` — `Server`/`Request`/`Handler`/`Route`/`Router`.
- `tests/test_m30.py` — runtime unit test + subprocess end-to-end tests.
- `examples/server.twl`, `README.md` — example + note.

---

## Task 1: `http_runtime.py` (Python socket primitives)

**Files:**
- Create: `tawla/http_runtime.py`
- Test: `tests/test_m30.py`

- [ ] **Step 1: Write the failing test** — Create `tests/test_m30.py`:

```python
"""M30: HTTP server core + routing."""

import http.client
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_http_runtime_roundtrip():
    from tawla.http_runtime import STATE
    STATE.reset()
    sid = STATE.listen(0)
    port = STATE.port(sid)
    result = {}

    def client():
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("POST", "/hi", body="data")
        r = c.getresponse()
        result["status"] = r.status
        result["body"] = r.read().decode()
        c.close()

    t = threading.Thread(target=client)
    t.start()
    rid = STATE.accept(sid)
    assert STATE.method(rid) == "POST"
    assert STATE.path(rid) == "/hi"
    assert STATE.body(rid) == "data"
    STATE.respond(rid, 200, "okok")
    t.join(timeout=5)
    STATE.reset()
    assert result["status"] == 200
    assert result["body"] == "okok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python -m pytest tests/test_m30.py -q`
Expected: FAIL — `ModuleNotFoundError: tawla.http_runtime`.

- [ ] **Step 3: Create the runtime** — Create `tawla/http_runtime.py`:

```python
"""Native HTTP server primitives for Tawla, hosted in Python and handed to the
JIT via llvmlite's add_symbol (the same pattern as gc_runtime / io_runtime).

A single-threaded, one-request-at-a-time HTTP/1.1 server: `listen` opens a
socket, `accept` blocks and parses one request, the getters expose its parts,
and `respond` writes a reply and closes the connection.
"""

import ctypes
import socket

import llvmlite.binding as llvm

from .gc_runtime import HEAP

_REASONS = {
    200: "OK", 201: "Created", 204: "No Content",
    400: "Bad Request", 404: "Not Found", 500: "Internal Server Error",
}


class HttpState:
    def __init__(self):
        self.servers: dict = {}
        self.requests: dict = {}
        self._next = 1

    def reset(self) -> None:
        for s in self.servers.values():
            try:
                s.close()
            except OSError:
                pass
        for r in self.requests.values():
            try:
                r["conn"].close()
            except OSError:
                pass
        self.servers.clear()
        self.requests.clear()
        self._next = 1

    def _id(self) -> int:
        i = self._next
        self._next += 1
        return i

    def listen(self, port: int) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.listen(16)
        sid = self._id()
        self.servers[sid] = sock
        return sid

    def port(self, sid: int) -> int:
        return self.servers[sid].getsockname()[1]

    def accept(self, sid: int) -> int:
        conn, _ = self.servers[sid].accept()
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        request_line = lines[0].decode("latin-1") if lines and lines[0] else ""
        parts = request_line.split(" ")
        method = parts[0] if len(parts) > 0 else ""
        path = parts[1] if len(parts) > 1 else ""
        length = 0
        for ln in lines[1:]:
            key, sep, val = ln.partition(b":")
            if sep and key.strip().lower() == b"content-length":
                try:
                    length = int(val.strip())
                except ValueError:
                    length = 0
        body = rest
        while len(body) < length:
            chunk = conn.recv(4096)
            if not chunk:
                break
            body += chunk
        rid = self._id()
        self.requests[rid] = {
            "conn": conn,
            "method": method,
            "path": path,
            "body": body[:length].decode("utf-8", "replace") if length else "",
        }
        return rid

    def method(self, rid: int) -> str:
        return self.requests[rid]["method"]

    def path(self, rid: int) -> str:
        return self.requests[rid]["path"]

    def body(self, rid: int) -> str:
        return self.requests[rid]["body"]

    def respond(self, rid: int, status: int, body: str) -> None:
        req = self.requests.pop(rid, None)
        if req is None:
            return
        body_bytes = body.encode("utf-8")
        reason = _REASONS.get(status, "OK")
        head = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: text/plain\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("latin-1")
        try:
            req["conn"].sendall(head + body_bytes)
        finally:
            req["conn"].close()


STATE = HttpState()


def _alloc_str(s: str) -> int:
    data = s.encode("utf-8") + b"\x00"
    addr = HEAP.alloc(len(data))
    ctypes.memmove(addr, data, len(data))
    return addr


_c_listen = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32)(lambda p: STATE.listen(p))
_c_port = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32)(lambda s: STATE.port(s))
_c_accept = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32)(lambda s: STATE.accept(s))
_c_method = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int32)(lambda r: _alloc_str(STATE.method(r)))
_c_path = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int32)(lambda r: _alloc_str(STATE.path(r)))
_c_body = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int32)(lambda r: _alloc_str(STATE.body(r)))
_c_respond = ctypes.CFUNCTYPE(None, ctypes.c_int32, ctypes.c_int32, ctypes.c_char_p)(
    lambda r, st, b: STATE.respond(r, st, b.decode("utf-8") if b else "")
)

_CALLBACKS = [_c_listen, _c_port, _c_accept, _c_method, _c_path, _c_body, _c_respond]
_registered = False


def install() -> None:
    """Register the HTTP primitives with llvmlite, then clear state for a run."""
    global _registered
    if not _registered:
        cast = ctypes.cast
        llvm.add_symbol("__http_listen", cast(_c_listen, ctypes.c_void_p).value)
        llvm.add_symbol("__http_port", cast(_c_port, ctypes.c_void_p).value)
        llvm.add_symbol("__http_accept", cast(_c_accept, ctypes.c_void_p).value)
        llvm.add_symbol("__http_method", cast(_c_method, ctypes.c_void_p).value)
        llvm.add_symbol("__http_path", cast(_c_path, ctypes.c_void_p).value)
        llvm.add_symbol("__http_body", cast(_c_body, ctypes.c_void_p).value)
        llvm.add_symbol("__http_respond", cast(_c_respond, ctypes.c_void_p).value)
        _registered = True
    STATE.reset()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python -m pytest tests/test_m30.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add tawla/http_runtime.py tests/test_m30.py
git commit -m "Add http_runtime: native socket HTTP primitives"
```

---

## Task 2: Wire `__http_*` builtins into the compiler

**Files:**
- Modify: `tawla/sema.py`, `tawla/codegen.py`, `tawla/compiler.py`
- Test: `tests/test_m30.py`

- [ ] **Step 1: Write the failing test** — Append to `tests/test_m30.py`:

```python
def run_server_once(tmp_path, src, method="GET", path="/", body=None):
    """Run a Tawla server program that binds port 0, prints the port, handles
    one request, and exits. Returns (status, response_body)."""
    prog = tmp_path / "srv.twl"
    prog.write_text(src, encoding="utf-8")
    p = subprocess.Popen(
        [sys.executable, "-m", "tawla", "run", str(prog)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT,
    )
    try:
        port_line = p.stdout.readline().strip()
        port = int(port_line)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(method, path, body=body)
        resp = conn.getresponse()
        out = (resp.status, resp.read().decode())
        conn.close()
        p.wait(timeout=5)
        return out
    finally:
        if p.poll() is None:
            p.kill()


def test_raw_primitives_end_to_end(tmp_path):
    # Echo the request path back as the body, using the raw __http_* builtins.
    src = (
        "class Main { void main() {"
        " int s = __http_listen(0); print(__http_port(s));"
        " int r = __http_accept(s); __http_respond(r, 200, __http_path(r)); } }"
    )
    status, body = run_server_once(tmp_path, src, path="/hello")
    assert status == 200
    assert body == "/hello"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python -m pytest tests/test_m30.py::test_raw_primitives_end_to_end -q`
Expected: FAIL — sema "call to undefined function '__http_listen'".

- [ ] **Step 3: Register the builtins in sema** — In `tawla/sema.py`, add to the `_BUILTINS` dict (after `"panic"`):

```python
    "__http_listen": ([INT], INT),
    "__http_port": ([INT], INT),
    "__http_accept": ([INT], INT),
    "__http_method": ([INT], STRING),
    "__http_path": ([INT], STRING),
    "__http_body": ([INT], STRING),
    "__http_respond": ([INT, INT, STRING], VOID),
```

- [ ] **Step 4: Declare the externs in codegen** — In `tawla/codegen.py`, in `_declare_runtime` (after the `io_read_*` declarations), add:

```python
        i32_to_i32 = ir.FunctionType(i32, [i32])
        self.http_listen = ir.Function(self.module, i32_to_i32, name="__http_listen")
        self.http_port = ir.Function(self.module, i32_to_i32, name="__http_port")
        self.http_accept = ir.Function(self.module, i32_to_i32, name="__http_accept")
        i32_to_str = ir.FunctionType(i8ptr, [i32])
        self.http_method = ir.Function(self.module, i32_to_str, name="__http_method")
        self.http_path = ir.Function(self.module, i32_to_str, name="__http_path")
        self.http_body = ir.Function(self.module, i32_to_str, name="__http_body")
        self.http_respond = ir.Function(
            self.module, ir.FunctionType(void, [i32, i32, i8ptr]), name="__http_respond"
        )
```

(`void` is the local `ir.VoidType()` already defined in `_declare_runtime`.)

- [ ] **Step 5: Emit the calls in `_gen_builtin`** — In `tawla/codegen.py`, in `_gen_builtin` (before the final `raise CodeGenError`):

```python
        if name == "__http_listen":
            return self.builder.call(self.http_listen, [self._gen_expr(args[0])])
        if name == "__http_port":
            return self.builder.call(self.http_port, [self._gen_expr(args[0])])
        if name == "__http_accept":
            self._flush_stdout()
            return self.builder.call(self.http_accept, [self._gen_expr(args[0])])
        if name == "__http_method":
            return self.builder.call(self.http_method, [self._gen_expr(args[0])])
        if name == "__http_path":
            return self.builder.call(self.http_path, [self._gen_expr(args[0])])
        if name == "__http_body":
            return self.builder.call(self.http_body, [self._gen_expr(args[0])])
        if name == "__http_respond":
            rid = self._gen_expr(args[0])
            status = self._gen_expr(args[1])
            body = self._gen_expr(args[2])
            return self.builder.call(self.http_respond, [rid, status, body])
```

- [ ] **Step 6: Install the runtime** — In `tawla/compiler.py`, change the import and add the install call:

```python
from . import gc_runtime, io_runtime, http_runtime
```

and next to `io_runtime.install()`:

```python
    gc_runtime.install()
    io_runtime.install()
    http_runtime.install()
```

- [ ] **Step 7: Run test to verify it passes**

Run: `./venv/Scripts/python -m pytest tests/test_m30.py -q`
Expected: PASS (2 passed).

- [ ] **Step 8: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add tawla/sema.py tawla/codegen.py tawla/compiler.py tests/test_m30.py
git commit -m "Wire __http_* primitives into sema, codegen, and the runtime"
```

---

## Task 3: `Http.twl` — Server / Request / Router

**Files:**
- Create: `tawla/stdlib/Http.twl`
- Test: `tests/test_m30.py`

- [ ] **Step 1: Write the failing tests** — Append to `tests/test_m30.py`:

```python
RAW = (
    'import "Http.twl";'
    " class Main { void main() {"
    " Server s = new Server(0); print(s.port());"
    " Request r = s.accept(); r.respond(200, r.path()); } }"
)

ROUTER = (
    'import "Http.twl";'
    ' class Hi : Handler { public void handle(Request req) { req.respond(200, "hello"); } }'
    " class Main { void main() {"
    " Router router = new Router(); router.get(\"/hi\", new Hi());"
    " Server s = new Server(0); print(s.port());"
    " router.handle(s.accept()); } }"
)


def test_server_request_api(tmp_path):
    status, body = run_server_once(tmp_path, RAW, path="/abc")
    assert status == 200
    assert body == "/abc"


def test_request_body_echo(tmp_path):
    src = (
        'import "Http.twl";'
        " class Main { void main() {"
        " Server s = new Server(0); print(s.port());"
        " Request r = s.accept(); r.respond(200, r.body()); } }"
    )
    status, body = run_server_once(tmp_path, src, method="POST", path="/x", body="payload")
    assert status == 200
    assert body == "payload"


def test_router_matches_route(tmp_path):
    status, body = run_server_once(tmp_path, ROUTER, path="/hi")
    assert status == 200
    assert body == "hello"


def test_router_404_for_unknown(tmp_path):
    status, body = run_server_once(tmp_path, ROUTER, path="/nope")
    assert status == 404
    assert body == "not found"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m30.py -q -k "server_request or body_echo or router"`
Expected: FAIL — `LoadError: cannot find imported file 'Http.twl'`.

- [ ] **Step 3: Create the stdlib module** — Create `tawla/stdlib/Http.twl`:

```tawla
// Tawla's HTTP server library. Import with:  import "Http.twl";
//
// Single-threaded HTTP/1.1. Drive it from your own loop with Server.accept(),
// or register handlers on a Router and call Server.serve(router).

import "Collections.twl";

class Request {
    private int id;
    public Request(int id) { this.id = id; }
    public string method() { return __http_method(this.id); }
    public string path() { return __http_path(this.id); }
    public string body() { return __http_body(this.id); }
    public void respond(int status, string body) { __http_respond(this.id, status, body); }
}

interface Handler {
    void handle(Request req);
}

class Route {
    public string method;
    public string path;
    public Handler handler;
    public Route(string m, string p, Handler h) {
        this.method = m;
        this.path = p;
        this.handler = h;
    }
}

class Router {
    private List<Route> routes;

    public Router() { this.routes = new List<Route>(); }

    public void get(string path, Handler h) { this.routes.add(new Route("GET", path, h)); }
    public void post(string path, Handler h) { this.routes.add(new Route("POST", path, h)); }

    public void handle(Request req) {
        int i = 0;
        while (i < this.routes.size()) {
            Route r = this.routes.get(i);
            if (r.method == req.method() && r.path == req.path()) {
                r.handler.handle(req);
                return;
            }
            i = i + 1;
        }
        req.respond(404, "not found");
    }
}

class Server {
    private int id;
    public Server(int port) { this.id = __http_listen(port); }
    public int port() { return __http_port(this.id); }
    public Request accept() { return new Request(__http_accept(this.id)); }
    public void serve(Router router) {
        while (true) {
            router.handle(this.accept());
        }
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m30.py -q`
Expected: PASS (all M30 tests).

- [ ] **Step 5: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tawla/stdlib/Http.twl tests/test_m30.py
git commit -m "Add Http.twl: Server, Request, and Express-style Router"
```

---

## Task 4: Example, README, final verification

**Files:**
- Create: `examples/server.twl`
- Modify: `README.md`

- [ ] **Step 1: Write the example** — Create `examples/server.twl`:

```tawla
// A tiny HTTP server with Express-style routing.
// Run it, then in another terminal:  curl localhost:8080/health
import "Http.twl";

class Health : Handler {
    public void handle(Request req) { req.respond(200, "ok"); }
}

class Echo : Handler {
    public void handle(Request req) { req.respond(200, req.body()); }
}

class Main {
    void main() {
        Router router = new Router();
        router.get("/health", new Health());
        router.post("/echo", new Echo());

        print("listening on http://localhost:8080");
        new Server(8080).serve(router);
    }
}
```

- [ ] **Step 2: Smoke-test the example by hand** — Start it, hit it, stop it:

Run (in one shell):
```
./venv/Scripts/python -m tawla run examples/server.twl
```
In another shell: `curl -s localhost:8080/health` → expect `ok`. Then stop the
server with Ctrl-C. (This is a manual check; the automated coverage is the
subprocess tests in Task 3.)

- [ ] **Step 3: Add a README bullet** — In `README.md`, under "What the language can do", after the collections bullet:

```markdown
- **HTTP server:** `import "Http.twl";` gives you a `Server`, a `Request`
  (`method`/`path`/`body`/`respond`), and an Express-style `Router` with
  `Handler` classes — `router.get("/health", new Health())` then
  `new Server(8080).serve(router)`. Single-threaded, minimal HTTP/1.1.
```

- [ ] **Step 4: Final full-suite run**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add examples/server.twl README.md
git commit -m "Add HTTP server example and README note"
```

---

## Self-review

**Spec coverage:**
- `Server`/`Request`/`Handler`/`Route`/`Router` API → Task 3 (`Http.twl`) + Task 3 tests. ✓
- Native `__http_*` primitives (listen/port/accept/method/path/body/respond) → Task 1 (`http_runtime.py`) + roundtrip unit test. ✓
- GC-allocated result strings → Task 1 (`_alloc_str` via `HEAP`). ✓
- builtins in sema/codegen; `__http_accept` flushes stdout first → Task 2 (Steps 3–5). ✓
- `install()` wired → Task 2 Step 6. ✓
- `Router` stores `List<Route>` (object pointers, no interface arrays); matches with `&&`; 404 fallback → Task 3 `Http.twl` + `test_router_*`. ✓
- `Http.twl` imports `Collections.twl` (nested stdlib import) → Task 3. ✓
- packaging via existing `stdlib/*.twl` rule → no task needed; tests import `Http.twl` to confirm resolution. ✓
- Testing approach (port-0 subprocess, read port, `http.client`) → `run_server_once` (Task 2) + cases (Tasks 2–3). ✓
- Example + README → Task 4. ✓
- Limits documented in README/spec; not implemented → correct. ✓

**Placeholder scan:** No TBD/TODO; every code/test step shows full content; commands have expected output. The example smoke-test (Task 4 Step 2) is an explicit manual check, not automated — the real coverage is the Task 3 subprocess tests.

**Type consistency:** Builtin names identical across `http_runtime` symbols, sema `_BUILTINS`, codegen externs, and `Http.twl` call sites (`__http_listen/port/accept/method/path/body/respond`). Signatures line up: `listen/port/accept` `(i32)->i32`, `method/path/body` `(i32)->i8*`, `respond` `(i32,i32,i8*)->void`. `Http.twl` method/ctor names (`accept`/`port`/`serve`/`respond`/`get`/`post`/`handle`) match the tests' call sites; `Server`/`Request`/`Route` ctors are `public`. `Router` uses `List<Route>` from the imported `Collections.twl`. ✓
