# JSON Write Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `Json` values and serialize them (`jsonObject`/`jsonArray`, typed mutators, `toString`), add `Map.keys()`, and let an HTTP handler return JSON via `respondJson`.

**Architecture:** Mostly Tawla stdlib (`Json.twl` builders/serializer reusing the read-milestone `Json` type; `Collections.twl` gains `keys()`). One compiler-side change: `__http_respond` takes a content-type so `Http.twl` can offer `respond` (text/plain) and `respondJson` (application/json).

**Tech Stack:** Tawla stdlib + Python `http_runtime`; tests via `run_twl` and a server subprocess.

**Reference spec:** `docs/superpowers/specs/2026-06-02-json-write-design.md`

**Milestone:** M33 — additive, ships as **1.3.0** (release is a separate user-triggered step).

---

## File structure

- `tawla/stdlib/Collections.twl` — add `Map.keys()`.
- `tawla/stdlib/Json.twl` — add builders, mutators, `toString`, `jsonEscape`.
- `tawla/http_runtime.py`, `tawla/sema.py`, `tawla/codegen.py`, `tawla/stdlib/Http.twl` — content-type on respond + `respondJson`.
- `tests/test_m33.py` — new tests; `tests/test_m30.py` — migrate one raw call.
- `examples/json_write.twl`, `README.md` — example + note.

---

## Task 1: `Map.keys()`

**Files:**
- Modify: `tawla/stdlib/Collections.twl`
- Test: `tests/test_m33.py`

- [ ] **Step 1: Write the failing test** — Create `tests/test_m33.py`:

```python
"""M33: JSON write (builders, toString, respondJson) + Map.keys."""

import http.client
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_map_keys(run_twl):
    src = (
        'import "Collections.twl";'
        " class Main { void main() {"
        ' Map<string, int> m = new Map<string, int>();'
        ' m.put("a", 1); m.put("b", 2); m.put("c", 3);'
        " List<string> ks = m.keys();"
        " print(ks.size()); print(ks.get(0)); print(ks.get(2)); } }"
    )
    assert run_twl(src).stdout == "3\na\nc\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python -m pytest tests/test_m33.py -q`
Expected: FAIL — `type 'Map$string$int' has no method 'keys'`.

- [ ] **Step 3: Add `keys()` to `Map`** — In `tawla/stdlib/Collections.twl`, inside `class Map<K, V>`, add a method (e.g. after `has`):

```tawla
    public List<K> keys() {
        List<K> result = new List<K>();
        int i = 0;
        while (i < this.count) {
            result.add(this.keys[i]);
            i = i + 1;
        }
        return result;
    }
```

(The `keys` *field* and the `keys()` *method* coexist — fields and methods are separate namespaces, and `this.keys[i]` is a field access while `m.keys()` is a call.)

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/Scripts/python -m pytest tests/test_m33.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tawla/stdlib/Collections.twl tests/test_m33.py
git commit -m "Add Map.keys() to Collections"
```

---

## Task 2: Json builders + `toString`

**Files:**
- Modify: `tawla/stdlib/Json.twl`
- Test: `tests/test_m33.py`

- [ ] **Step 1: Write the failing tests** — Append to `tests/test_m33.py`:

```python
def _main(body):
    return 'import "Json.twl"; class Main { void main() { ' + body + " } }"


def test_build_object(run_twl):
    src = _main(
        "Json o = jsonObject();"
        ' o.setString("status", "ok"); o.setInt("count", 3);'
        " print(o.toString());"
    )
    assert run_twl(src).stdout == '{"status":"ok","count":3}\n'


def test_build_array(run_twl):
    src = _main(
        "Json a = jsonArray(); a.pushInt(1); a.pushInt(2); a.pushBool(true);"
        " print(a.toString());"
    )
    assert run_twl(src).stdout == "[1,2,true]\n"


def test_build_nested(run_twl):
    src = _main(
        "Json o = jsonObject(); Json a = jsonArray();"
        ' a.pushString("x"); a.pushString("y"); o.set("items", a);'
        " print(o.toString());"
    )
    assert run_twl(src).stdout == '{"items":["x","y"]}\n'


def test_round_trip(run_twl):
    src = _main(
        "Json o = jsonObject(); o.setInt(\"n\", 42);"
        " Json back = parseJson(o.toString()); print(back.get(\"n\").asInt());"
    )
    assert run_twl(src).stdout == "42\n"


def test_escaping_round_trip(run_twl):
    # a value containing a quote and newline serializes with escapes and re-parses
    src = _main(
        'Json o = jsonObject(); o.setString("k", "a\\"b\\nc");'
        ' Json back = parseJson(o.toString());'
        ' print(back.get("k").asString().length);'
    )
    # "a\"b\nc" decoded = a " b <newline> c = 5 chars
    assert run_twl(src).stdout == "5\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m33.py -q -k "build or round_trip or escaping"`
Expected: FAIL — `call to undefined function 'jsonObject'`.

- [ ] **Step 3: Add builders + mutators + `toString`** — In `tawla/stdlib/Json.twl`, add these methods inside `class Json` (e.g. after `get`):

```tawla
    public void setString(string key, string v) {
        Json n = new Json(); n.kind = 3; n.strVal = v; this.obj.put(key, n);
    }
    public void setInt(string key, int v) {
        Json n = new Json(); n.kind = 2; n.numVal = v; this.obj.put(key, n);
    }
    public void setFloat(string key, float v) {
        Json n = new Json(); n.kind = 2; n.numVal = v; this.obj.put(key, n);
    }
    public void setBool(string key, bool v) {
        Json n = new Json(); n.kind = 1; n.boolVal = v; this.obj.put(key, n);
    }
    public void set(string key, Json v) { this.obj.put(key, v); }

    public void pushString(string v) {
        Json n = new Json(); n.kind = 3; n.strVal = v; this.arr.add(n);
    }
    public void pushInt(int v) {
        Json n = new Json(); n.kind = 2; n.numVal = v; this.arr.add(n);
    }
    public void pushFloat(float v) {
        Json n = new Json(); n.kind = 2; n.numVal = v; this.arr.add(n);
    }
    public void pushBool(bool v) {
        Json n = new Json(); n.kind = 1; n.boolVal = v; this.arr.add(n);
    }
    public void push(Json v) { this.arr.add(v); }

    public string toString() {
        if (this.kind == 0) { return "null"; }
        if (this.kind == 1) {
            if (this.boolVal) { return "true"; }
            return "false";
        }
        if (this.kind == 2) { return toString(this.numVal); }
        if (this.kind == 3) { return "\"" + jsonEscape(this.strVal) + "\""; }
        if (this.kind == 4) {
            string s = "[";
            int i = 0;
            while (i < this.arr.size()) {
                if (i > 0) { s = s + ","; }
                s = s + this.arr.get(i).toString();
                i = i + 1;
            }
            return s + "]";
        }
        string s = "{";
        List<string> ks = this.obj.keys();
        int i = 0;
        while (i < ks.size()) {
            if (i > 0) { s = s + ","; }
            string k = ks.get(i);
            s = s + "\"" + jsonEscape(k) + "\":" + this.obj.get(k).toString();
            i = i + 1;
        }
        return s + "}";
    }
```

And add these free functions at the end of `Json.twl` (next to `parseJson`):

```tawla
Json jsonObject() {
    Json j = new Json();
    j.kind = 5;
    j.obj = new Map<string, Json>();
    return j;
}

Json jsonArray() {
    Json j = new Json();
    j.kind = 4;
    j.arr = new List<Json>();
    return j;
}

string jsonEscape(string s) {
    string out = "";
    int i = 0;
    while (i < s.length) {
        int c = charAt(s, i);
        if (c == 34)      { out = out + "\\\""; }
        else if (c == 92) { out = out + "\\\\"; }
        else if (c == 10) { out = out + "\\n"; }
        else if (c == 9)  { out = out + "\\t"; }
        else if (c == 13) { out = out + "\\r"; }
        else { out = out + substring(s, i, i + 1); }
        i = i + 1;
    }
    return out;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m33.py -q`
Expected: PASS (Map.keys + build/round-trip/escaping).

- [ ] **Step 5: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tawla/stdlib/Json.twl tests/test_m33.py
git commit -m "Add JSON builders and toString serializer"
```

---

## Task 3: HTTP content-type + respondJson

**Files:**
- Modify: `tawla/http_runtime.py`, `tawla/sema.py`, `tawla/codegen.py`, `tawla/stdlib/Http.twl`
- Modify: `tests/test_m30.py` (migrate one call)
- Test: `tests/test_m33.py`

- [ ] **Step 1: Write the failing test** — Append to `tests/test_m33.py`:

```python
def _run_server_once(tmp_path, src, method="GET", path="/", body=None):
    prog = tmp_path / "srv.twl"
    prog.write_text(src, encoding="utf-8")
    p = subprocess.Popen(
        [sys.executable, "-m", "tawla", "run", str(prog)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT,
    )
    try:
        port = int(p.stdout.readline().strip())
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(method, path, body=body)
        resp = conn.getresponse()
        out = (resp.status, resp.getheader("Content-Type"), resp.read().decode())
        conn.close()
        p.wait(timeout=5)
        return out
    finally:
        if p.poll() is None:
            p.kill()


def test_respond_json_sets_content_type(tmp_path):
    src = (
        'import "Http.twl";'
        " class Main { void main() {"
        " Server s = new Server(0); print(s.port());"
        ' Request r = s.accept(); r.respondJson(200, "{\\"ok\\":true}"); } }'
    )
    status, ctype, body = _run_server_once(tmp_path, src)
    assert status == 200
    assert ctype == "application/json"
    assert body == '{"ok":true}'


def test_respond_stays_text_plain(tmp_path):
    src = (
        'import "Http.twl";'
        " class Main { void main() {"
        " Server s = new Server(0); print(s.port());"
        ' Request r = s.accept(); r.respond(200, "hi"); } }'
    )
    status, ctype, body = _run_server_once(tmp_path, src)
    assert status == 200
    assert ctype == "text/plain"
    assert body == "hi"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python -m pytest tests/test_m33.py -q -k "respond"`
Expected: FAIL — `Request` has no method `respondJson`.

- [ ] **Step 3: Add content-type to the runtime** — In `tawla/http_runtime.py`, change `respond` and its CFUNCTYPE:

```python
    def respond(self, rid: int, status: int, content_type: str, body: str) -> None:
        req = self.requests.pop(rid, None)
        if req is None:
            return
        body_bytes = body.encode("utf-8")
        reason = _REASONS.get(status, "OK")
        head = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("latin-1")
        try:
            req["conn"].sendall(head + body_bytes)
        finally:
            req["conn"].close()
```

And replace the `_c_respond` callback:

```python
_c_respond = ctypes.CFUNCTYPE(None, ctypes.c_int32, ctypes.c_int32, ctypes.c_char_p, ctypes.c_char_p)(
    lambda r, st, ct, b: STATE.respond(
        r, st, ct.decode("utf-8") if ct else "text/plain", b.decode("utf-8") if b else ""
    )
)
```

- [ ] **Step 4: Update the builtin signature in sema** — In `tawla/sema.py`, change the `__http_respond` entry in `_BUILTINS`:

```python
    "__http_respond": ([INT, INT, STRING, STRING], VOID),
```

- [ ] **Step 5: Update codegen** — In `tawla/codegen.py`, change the `__http_respond` extern declaration in `_declare_runtime`:

```python
        self.http_respond = ir.Function(
            self.module, ir.FunctionType(void, [i32, i32, i8ptr, i8ptr]), name="__http_respond"
        )
```

And the `_gen_builtin` branch:

```python
        if name == "__http_respond":
            rid = self._gen_expr(args[0])
            status = self._gen_expr(args[1])
            ctype = self._gen_expr(args[2])
            body = self._gen_expr(args[3])
            return self.builder.call(self.http_respond, [rid, status, ctype, body])
```

- [ ] **Step 6: Update `Http.twl`** — In `tawla/stdlib/Http.twl`, change `Request.respond` and add `respondJson`:

```tawla
    public void respond(int status, string body) {
        __http_respond(this.id, status, "text/plain", body);
    }
    public void respondJson(int status, string body) {
        __http_respond(this.id, status, "application/json", body);
    }
```

- [ ] **Step 7: Migrate the raw `test_m30` call** — In `tests/test_m30.py`, in `test_raw_primitives_end_to_end`, change the respond call to pass a content-type:

```python
        " int r = __http_accept(s); __http_respond(r, 200, \"text/plain\", __http_path(r)); } }"
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `./venv/Scripts/python -m pytest tests/test_m33.py tests/test_m30.py -q`
Expected: PASS.

- [ ] **Step 9: Run the full suite**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add tawla/http_runtime.py tawla/sema.py tawla/codegen.py tawla/stdlib/Http.twl tests/test_m33.py tests/test_m30.py
git commit -m "Add Content-Type to HTTP respond and Request.respondJson"
```

---

## Task 4: Example, README, final verification

**Files:**
- Create: `examples/json_write.twl`
- Modify: `README.md`

- [ ] **Step 1: Write the example** — Create `examples/json_write.twl`:

```tawla
// Building and serializing JSON.
import "Json.twl";

class Main {
    void main() {
        Json user = jsonObject();
        user.setString("name", "Ada");
        user.setInt("age", 36);

        Json langs = jsonArray();
        langs.pushString("twl");
        langs.pushString("py");
        user.set("langs", langs);

        print(user.toString());
        // {"name":"Ada","age":36,"langs":["twl","py"]}
    }
}
```

- [ ] **Step 2: Run the example**

Run: `./venv/Scripts/python -m tawla run examples/json_write.twl`
Expected output:
```
{"name":"Ada","age":36,"langs":["twl","py"]}
```

- [ ] **Step 3: Add a README bullet** — In `README.md`, replace the "JSON (read)" bullet's wording to mention write, or add after it:

```markdown
- **JSON (write):** build values with `jsonObject()` / `jsonArray()` and
  `setString`/`setInt`/`setBool`/`set` / `pushString`/`push`, then `toString()`
  to serialize. In an HTTP handler, `req.respondJson(200, out.toString())` sends
  it with `Content-Type: application/json`.
```

- [ ] **Step 4: Final full-suite run**

Run: `./venv/Scripts/python -m pytest -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add examples/json_write.twl README.md
git commit -m "Add JSON-write example and README note"
```

---

## Self-review

**Spec coverage:**
- `jsonObject`/`jsonArray` free functions → Task 2. ✓
- object mutators `setString/setInt/setFloat/setBool/set` + array `pushString/pushInt/pushFloat/pushBool/push` → Task 2. ✓
- `toString()` recursive serializer with escaping → Task 2 (`toString` + `jsonEscape`) + `test_build_*`/`test_escaping_round_trip`. ✓
- `Map.keys()` → Task 1 + `test_map_keys`; used by `toString` objects. ✓
- HTTP content-type plumbing (runtime + sema + codegen + Http.twl `respond`/`respondJson`) → Task 3. ✓
- `test_m30` 3-arg → 4-arg migration → Task 3 Step 7. ✓
- round-trip with `parseJson` → Task 2 `test_round_trip`/`test_escaping_round_trip`. ✓
- respondJson Content-Type + body verified via server subprocess → Task 3 `test_respond_json_sets_content_type`; `respond` text/plain check too. ✓
- Example + README → Task 4. ✓
- Limitations documented (kind not guarded, %g numbers, escape set) → spec/README. ✓

**Placeholder scan:** No TBD/TODO; full code in every step; commands have expected output.

**Type consistency:** `toString` is a `Json` method; `toString(this.numVal)` is the *builtin* `Call` (free function), distinct from the `j.toString()` *MethodCall* — no conflict. `jsonObject`/`jsonArray`/`jsonEscape`/`parseJson` are free functions in `Json.twl`. `Map.keys()` returns `List<K>`; `Json.obj` is `Map<string, Json>` so `this.obj.keys()` is `List<string>`. `__http_respond` signature `(i32,i32,i8*,i8*)` matches across http_runtime / sema / codegen / Http.twl call sites and the migrated test. `respond`/`respondJson` arg order `(status, body)` matches the tests. ✓
