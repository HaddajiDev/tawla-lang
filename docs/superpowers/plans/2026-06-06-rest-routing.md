# Real REST Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add path params (`/users/:id`), query-string params, and request-header access to Tawla's HTTP router.

**Architecture:** The Python `http_runtime` parses the request-target into a clean path + a query dict and stores all headers (lower-cased); it exposes `__http_query`/`__http_header` (null when absent) and makes `__http_path` return the clean path. The `Router` (pure Tawla in `Http.twl`) matches `:name` patterns segment-wise and binds captured params onto the `Request`.

**Tech Stack:** Python 3.11+, llvmlite, the Tawla compiler, pytest (`http.client` + subprocess server harness, as in `tests/test_m30.py`).

**Reference spec:** `docs/superpowers/specs/2026-06-06-rest-routing-design.md`

---

## Verified facts (from the codebase)

- `http_runtime.accept()` (~line 60) stores `requests[rid] = {conn, method, path, body}`; `path` is currently the raw request-target (query string included). Headers are read only for `Content-Length`.
- String args reach runtime wrappers as `c_char_p` (bytes), decoded `x.decode("utf-8") if x else ""` (see `_c_respond`, line 140). `_alloc_str(s)` (line 127) GC-allocates a NUL-terminated copy and returns its address; returning `0` yields a null `char*` → Tawla `null`.
- Builtins are declared in `sema.py` `_BUILTINS` (lines ~115-117: `__http_method/path/body` → `([INT], STRING)`) and in `codegen.py` (decls ~153-155 via `i32_to_str = FunctionType(i8ptr,[i32])`; dispatch ~1015-1019). Multi-arg example: `__http_respond` decl `FunctionType(void,[i32,i32,i8ptr,i8ptr])` (line ~156) and dispatch (~1020).
- `Http.twl` `Request`: fields `private int id`; methods `method()/path()/body()` call `__http_*`; `respond/respondJson`. `Router`: `List<Route> routes`, `get/post`, `handle` does `r.method == req.method() && r.path == req.path()` exact match, else 404. It already `import "Collections.twl";` (List/Map available).
- String ops: `s.length` (property), `charAt(s, i)` → int char code, `substring(s, a, b)` (end exclusive). `'/'` = 47, `':'` = 58. `Map`: `put`, `get` (returns `null` for a missing key), `has`, `size`.
- Test harness: `tests/test_m30.py` has `run_server_once(tmp_path, src, method, path, body)` — runs a Tawla server that prints its port, handles one request, exits; returns `(status, body)`. It does **not** send custom headers.

## File Structure

| File | Change |
|------|--------|
| `tawla/http_runtime.py` | Clean path + query dict + headers dict in `accept()`; `STATE.query`/`STATE.header`; `__http_query`/`__http_header` wrappers + registration |
| `tawla/sema.py` | Declare `__http_query`/`__http_header` builtins |
| `tawla/codegen.py` | Declare + dispatch `__http_query`/`__http_header` |
| `tawla/stdlib/Http.twl` | `Request` param/query/header + params map; `Router` segment matching |
| `tests/test_m37.py` | New tests (runtime + end-to-end routing) |
| `examples/rest_api.twl`, `README.md`, `tawla_lang_docs/index.html`, `pyproject.toml`, `tawla/__init__.py` | Example, docs, version 1.6.0 |

---

## Task 1: Runtime — clean path, query, and headers

**Files:**
- Modify: `tawla/http_runtime.py`
- Test: `tests/test_m37.py` (new)

- [ ] **Step 1: Write the failing runtime test**

Create `tests/test_m37.py`:

```python
"""M37: real REST routing — path params, query, headers."""

import http.client
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_runtime_query_header_and_clean_path():
    from tawla.http_runtime import STATE
    STATE.reset()
    sid = STATE.listen(0)
    port = STATE.port(sid)

    def client():
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/users/42?q=hi&page=2", headers={"X-Test": "hello"})
        c.getresponse().read()
        c.close()

    t = threading.Thread(target=client)
    t.start()
    rid = STATE.accept(sid)
    assert STATE.path(rid) == "/users/42"          # query stripped
    assert STATE.query(rid, "q") == "hi"
    assert STATE.query(rid, "page") == "2"
    assert STATE.query(rid, "missing") is None
    assert STATE.header(rid, "x-test") == "hello"   # case-insensitive
    assert STATE.header(rid, "absent") is None
    STATE.respond(rid, 200, "text/plain", "ok")
    t.join(timeout=5)
    STATE.reset()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_m37.py::test_runtime_query_header_and_clean_path -v`
Expected: FAIL — `STATE.query`/`STATE.header` don't exist and `path` still includes the query.

- [ ] **Step 3: Parse path/query/headers in `accept()`**

In `tawla/http_runtime.py` `accept()`, replace the request-line + content-length section and the stored dict. The current code is:

```python
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
```

Replace with:

```python
        request_line = lines[0].decode("latin-1") if lines and lines[0] else ""
        parts = request_line.split(" ")
        method = parts[0] if len(parts) > 0 else ""
        target = parts[1] if len(parts) > 1 else ""
        raw_path, _, query_str = target.partition("?")
        from urllib.parse import parse_qs
        query = {k: v[0] for k, v in parse_qs(query_str, keep_blank_values=True).items()}
        headers = {}
        length = 0
        for ln in lines[1:]:
            key, sep, val = ln.partition(b":")
            if not sep:
                continue
            name = key.strip().decode("latin-1").lower()
            value = val.strip().decode("latin-1")
            headers[name] = value
            if name == "content-length":
                try:
                    length = int(value)
                except ValueError:
                    length = 0
```

Then change the stored dict (just below, currently `{"conn", "method", "path", "body"}`) to use `raw_path` and add `query`/`headers`:

```python
        self.requests[rid] = {
            "conn": conn,
            "method": method,
            "path": raw_path,
            "query": query,
            "headers": headers,
            "body": body[:length].decode("utf-8", "replace") if length else "",
        }
```

- [ ] **Step 4: Add `query`/`header` accessors to `HttpState`**

Next to the existing `def body(self, rid)` method, add:

```python
    def query(self, rid: int, key: str):
        return self.requests[rid]["query"].get(key)

    def header(self, rid: int, key: str):
        return self.requests[rid]["headers"].get(key.lower())
```

- [ ] **Step 5: Run the runtime test**

Run: `venv/Scripts/python.exe -m pytest tests/test_m37.py::test_runtime_query_header_and_clean_path -v`
Expected: PASS.

- [ ] **Step 6: Add the C wrappers + register the symbols**

In `tawla/http_runtime.py`, after the `_c_body` line (~139), add:

```python
def _query(rid, key):
    v = STATE.query(rid, key.decode("utf-8") if key else "")
    return _alloc_str(v) if v is not None else 0


def _header(rid, key):
    v = STATE.header(rid, key.decode("utf-8") if key else "")
    return _alloc_str(v) if v is not None else 0


_c_query = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int32, ctypes.c_char_p)(_query)
_c_header = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int32, ctypes.c_char_p)(_header)
```

Add `_c_query, _c_header` to the `_CALLBACKS` list (line ~146). In `install()`, after the `__http_body` registration, add:

```python
        llvm.add_symbol("__http_query", cast(_c_query, ctypes.c_void_p).value)
        llvm.add_symbol("__http_header", cast(_c_header, ctypes.c_void_p).value)
```

- [ ] **Step 7: Commit**

```bash
git add tawla/http_runtime.py tests/test_m37.py
git commit -m "http_runtime: clean path + query/header parsing and accessors"
```

---

## Task 2: Wire `__http_query` / `__http_header` builtins

**Files:**
- Modify: `tawla/sema.py`, `tawla/codegen.py`

- [ ] **Step 1: Declare in sema**

In `tawla/sema.py`, in the `_BUILTINS` dict next to `__http_body` (line ~117), add:

```python
    "__http_query": ([INT, STRING], STRING),
    "__http_header": ([INT, STRING], STRING),
```

- [ ] **Step 2: Declare the functions in codegen**

In `tawla/codegen.py`, after `self.http_body = ...` (line ~155), add:

```python
        i32_str_to_str = ir.FunctionType(i8ptr, [i32, i8ptr])
        self.http_query = ir.Function(self.module, i32_str_to_str, name="__http_query")
        self.http_header = ir.Function(self.module, i32_str_to_str, name="__http_header")
```

- [ ] **Step 3: Dispatch them**

In `tawla/codegen.py`, after the `__http_body` dispatch (line ~1019), add:

```python
        if name == "__http_query":
            return self.builder.call(self.http_query, [self._gen_expr(args[0]), self._gen_expr(args[1])])
        if name == "__http_header":
            return self.builder.call(self.http_header, [self._gen_expr(args[0]), self._gen_expr(args[1])])
```

- [ ] **Step 4: Smoke-test the builtins end to end**

Run this one-off to confirm the wiring (a server that echoes a query param):

```bash
venv/Scripts/python.exe - <<'PY'
import http.client, subprocess, sys, threading
src = ('class Main { void main() {'
       ' int s = __http_listen(0); print(__http_port(s));'
       ' int r = __http_accept(s); __http_respond(r, 200, "text/plain", __http_query(r, "q")); } }')
open("_t.twl","w").write(src)
p = subprocess.Popen([sys.executable,"-m","tawla","run","_t.twl"],stdout=subprocess.PIPE,text=True)
port=int(p.stdout.readline()); 
c=http.client.HTTPConnection("127.0.0.1",port,timeout=5); c.request("GET","/x?q=ping")
print("body:", c.getresponse().read().decode()); p.wait(timeout=5)
PY
rm -f _t.twl
```

Expected: `body: ping`.

- [ ] **Step 5: Run the full suite (no regressions in existing HTTP tests)**

Run: `venv/Scripts/python.exe -m pytest tests/test_m30.py -q`
Expected: PASS — existing routing tests use query-free paths, so the clean-path
change is transparent.

- [ ] **Step 6: Commit**

```bash
git add tawla/sema.py tawla/codegen.py
git commit -m "Wire __http_query / __http_header builtins (sema + codegen)"
```

---

## Task 3: `Http.twl` — Request accessors + Router param matching

**Files:**
- Modify: `tawla/stdlib/Http.twl`
- Test: `tests/test_m37.py`

- [ ] **Step 1: Write the failing end-to-end tests**

Append to `tests/test_m37.py` a header-capable server harness and the tests:

```python
def _serve(tmp_path, src, method="GET", path="/", body=None, headers=None):
    prog = tmp_path / "srv.twl"
    prog.write_text(src, encoding="utf-8")
    p = subprocess.Popen(
        [sys.executable, "-m", "tawla", "run", str(prog)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT,
    )
    try:
        port = int(p.stdout.readline().strip())
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        out = (resp.status, resp.read().decode())
        conn.close()
        p.wait(timeout=5)
        return out
    finally:
        if p.poll() is None:
            p.kill()


def _router_prog(handler_class, route_method, route_pattern, handler_body):
    return (
        'import "Http.twl";'
        f' class H : Handler {{ public void handle(Request req) {{ {handler_body} }} }}'
        ' class Main { void main() {'
        ' Router router = new Router();'
        f' router.{route_method}("{route_pattern}", new H());'
        ' Server s = new Server(0); print(s.port());'
        ' router.handle(s.accept()); } }'
    )


def test_path_param(tmp_path):
    src = _router_prog("H", "get", "/users/:id", 'req.respond(200, req.param("id"));')
    assert _serve(tmp_path, src, path="/users/42") == (200, "42")


def test_multi_param(tmp_path):
    src = _router_prog("H", "get", "/a/:x/b/:y",
                       'req.respond(200, req.param("x") + "-" + req.param("y"));')
    assert _serve(tmp_path, src, path="/a/1/b/2") == (200, "1-2")


def test_static_mismatch_404(tmp_path):
    src = _router_prog("H", "get", "/users/:id", 'req.respond(200, "x");')
    assert _serve(tmp_path, src, path="/accounts/5")[0] == 404


def test_segment_count_mismatch_404(tmp_path):
    src = _router_prog("H", "get", "/users/:id", 'req.respond(200, "x");')
    assert _serve(tmp_path, src, path="/users/5/extra")[0] == 404


def test_method_mismatch_404(tmp_path):
    src = _router_prog("H", "get", "/users/:id", 'req.respond(200, "x");')
    assert _serve(tmp_path, src, method="POST", path="/users/5", body="")[0] == 404


def test_query_present_and_path_clean(tmp_path):
    src = _router_prog("H", "get", "/search",
                       'req.respond(200, req.query("q") + "|" + req.path());')
    assert _serve(tmp_path, src, path="/search?q=hi&page=2") == (200, "hi|/search")


def test_query_absent_is_null(tmp_path):
    src = _router_prog("H", "get", "/search",
                       'string v = req.query("nope"); '
                       'if (v == null) { req.respond(200, "NULL"); } else { req.respond(200, v); }')
    assert _serve(tmp_path, src, path="/search") == (200, "NULL")


def test_header_case_insensitive(tmp_path):
    src = _router_prog("H", "get", "/h", 'req.respond(200, req.header("x-test"));')
    assert _serve(tmp_path, src, path="/h", headers={"X-Test": "hello"}) == (200, "hello")
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_m37.py -k "param or mismatch or query or header" -v`
Expected: FAIL — `Request` has no `param/query/header` and the `Router` does exact
matching (so `/users/42` against `/users/:id` 404s).

- [ ] **Step 3: Extend `Request` in `tawla/stdlib/Http.twl`**

Replace the `Request` class with:

```tawla
class Request {
    private int id;
    private Map<string, string> params;
    public Request(int id) {
        this.id = id;
        this.params = new Map<string, string>();
    }
    public string method() { return __http_method(this.id); }
    public string path() { return __http_path(this.id); }
    public string body() { return __http_body(this.id); }
    public string query(string name) { return __http_query(this.id, name); }
    public string header(string name) { return __http_header(this.id, name); }
    public string param(string name) { return this.params.get(name); }
    public void bindParam(string name, string value) { this.params.put(name, value); }
    public void respond(int status, string body) {
        __http_respond(this.id, status, "text/plain", body);
    }
    public void respondJson(int status, string body) {
        __http_respond(this.id, status, "application/json", body);
    }
}
```

- [ ] **Step 4: Add segment matching to the `Router`**

Replace the `Router` class with (keeps `get`/`post`, adds `splitPath`/`segMatch`/`bindParams`, rewrites `handle`):

```tawla
class Router {
    private List<Route> routes;

    public Router() { this.routes = new List<Route>(); }

    public void get(string path, Handler h) { this.routes.add(new Route("GET", path, h)); }
    public void post(string path, Handler h) { this.routes.add(new Route("POST", path, h)); }

    private List<string> splitPath(string p) {
        List<string> out = new List<string>();
        int n = p.length;
        int start = 0;
        int i = 0;
        while (i < n) {
            if (charAt(p, i) == 47) {            // '/'
                if (i > start) { out.add(substring(p, start, i)); }
                start = i + 1;
            }
            i = i + 1;
        }
        if (n > start) { out.add(substring(p, start, n)); }
        return out;
    }

    private bool isParam(string seg) {
        return seg.length > 0 && charAt(seg, 0) == 58;   // ':'
    }

    private bool segMatch(List<string> pat, List<string> act) {
        if (pat.size() != act.size()) { return false; }
        int i = 0;
        while (i < pat.size()) {
            string ps = pat.get(i);
            if (!this.isParam(ps)) {
                if (ps != act.get(i)) { return false; }
            }
            i = i + 1;
        }
        return true;
    }

    private void bindParams(List<string> pat, List<string> act, Request req) {
        int i = 0;
        while (i < pat.size()) {
            string ps = pat.get(i);
            if (this.isParam(ps)) {
                req.bindParam(substring(ps, 1, ps.length), act.get(i));
            }
            i = i + 1;
        }
    }

    public void handle(Request req) {
        List<string> act = this.splitPath(req.path());
        int i = 0;
        while (i < this.routes.size()) {
            Route r = this.routes.get(i);
            if (r.method == req.method()) {
                List<string> pat = this.splitPath(r.path);
                if (this.segMatch(pat, act)) {
                    this.bindParams(pat, act, req);
                    r.handler.handle(req);
                    return;
                }
            }
            i = i + 1;
        }
        req.respond(404, "not found");
    }
}
```

- [ ] **Step 5: Run the routing tests**

Run: `venv/Scripts/python.exe -m pytest tests/test_m37.py -v`
Expected: PASS (all M37 tests).

- [ ] **Step 6: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all pass (existing `test_m30.py` routing still green).

- [ ] **Step 7: Commit**

```bash
git add tawla/stdlib/Http.twl tests/test_m37.py
git commit -m "Router: path-param matching; Request param/query/header accessors"
```

---

## Task 4: Example, docs, version, verification

**Files:**
- Create: `examples/rest_api.twl`
- Modify: `README.md`, `tawla_lang_docs/index.html`, `pyproject.toml`, `tawla/__init__.py`

- [ ] **Step 1: Create the example**

Create `examples/rest_api.twl`:

```tawla
// A tiny REST API: path params, query strings, and request headers.
// Run it, then in another terminal:
//   curl localhost:8080/users/42
//   curl "localhost:8080/search?q=hello"
//   curl -H "X-Token: secret" localhost:8080/whoami
import "Http.twl";

class GetUser : Handler {
    public void handle(Request req) {
        req.respondJson(200, "{\"id\": \"" + req.param("id") + "\"}");
    }
}

class Search : Handler {
    public void handle(Request req) {
        string q = req.query("q");
        if (q == null) { q = "(none)"; }
        req.respond(200, "searching for: " + q);
    }
}

class WhoAmI : Handler {
    public void handle(Request req) {
        string tok = req.header("X-Token");
        if (tok == null) { req.respond(401, "no token"); }
        else { req.respond(200, "token: " + tok); }
    }
}

class Main {
    void main() {
        Router router = new Router();
        router.get("/users/:id", new GetUser());
        router.get("/search", new Search());
        router.get("/whoami", new WhoAmI());
        Server s = new Server(8080);
        print("listening on http://localhost:8080");
        s.serve(router);
    }
}
```

- [ ] **Step 2: Verify the example compiles/starts**

Run (starts a server; confirm it prints the listening line, then stop it):

```bash
cd /d/Projects/Tawla_lang
timeout 4 venv/Scripts/python.exe -m tawla run examples/rest_api.twl 2>&1 | head -1
```

Expected first line: `listening on http://localhost:8080` (a timeout kill after is fine — it serves forever).

- [ ] **Step 3: Update the README HTTP bullet**

In `README.md`, replace the existing HTTP-server bullet:

```markdown
- **HTTP server:** `import "Http.twl";` gives you a `Server`, a `Request`
  (`method`/`path`/`body`/`respond`), and an Express-style `Router` with
  `Handler` classes — `router.get("/health", new Health())` then
  `new Server(8080).serve(router)`. Single-threaded, minimal HTTP/1.1.
```

with:

```markdown
- **HTTP server:** `import "Http.twl";` gives you a `Server`, a `Request`, and an
  Express-style `Router` with `Handler` classes. Routes take path params —
  `router.get("/users/:id", new GetUser())` — and inside a handler `req.param("id")`,
  `req.query("page")`, and `req.header("Authorization")` read the path param,
  query string, and request header (each `null` when absent). `req.method()`/
  `path()`/`body()`/`respond()`/`respondJson()` round it out. Single-threaded,
  minimal HTTP/1.1.
```

- [ ] **Step 4: Update the docs site**

In `tawla_lang_docs/index.html`, in the `#http` section, after the existing
server code block, add a short paragraph + example showing path params, query,
and header (escape `<`/`>`/`&` as the other code blocks do):

```html
      <p>Routes can capture path params with <code>:name</code>. Inside a handler, <code>req.param("id")</code>, <code>req.query("page")</code>, and <code>req.header("Authorization")</code> read the path param, query string, and request header — each returns <code>null</code> when absent.</p>
      <div class="code">
        <div class="code-head"><span class="dot"></span><span class="fname">routes.twl</span><button class="copy-btn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg><span class="copy-label">Copy</span></button></div>
        <pre><code class="twl">class GetUser : Handler {
    public void handle(Request req) {
        req.respond(200, "user " + req.param("id"));
    }
}
// ...
router.get("/users/:id", new GetUser());</code></pre>
      </div>
```

- [ ] **Step 5: Bump version to 1.6.0**

`pyproject.toml` line 3 → `version = "1.6.0"`; `tawla/__init__.py` line 3 →
`__version__ = "1.6.0"`.

- [ ] **Step 6: Run the full suite + version check**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all pass.
Run: `venv/Scripts/python.exe -m tawla version`
Expected: `tawlac 1.6.0`.

- [ ] **Step 7: Commit (compiler repo) + push docs (separate repo)**

```bash
git add examples/rest_api.twl README.md pyproject.toml tawla/__init__.py
git commit -m "Add REST API example, docs, bump to 1.6.0"
```

```bash
cd D:\Projects\tawla_lang_docs
git add index.html
git commit -m "Document path params, query, and headers"
git push
cd D:\Projects\Tawla_lang
```

---

## Done criteria

- `router.get("/users/:id", ...)` matches `/users/42`; `req.param("id")` → `"42"`.
- `req.query(k)` / `req.header(k)` return values (header case-insensitive) or `null`.
- `req.path()` excludes the query string; segment-count, static, and method
  mismatches all 404; existing exact routes still work.
- `tests/test_m37.py` + full suite green; `tawlac version` → `1.6.0`.

## Release (on the user's go-ahead)

Merge to `main`, push, `git tag v1.6.0 && git push origin v1.6.0` (builds the
binaries), then build + publish 1.6.0 to PyPI.
