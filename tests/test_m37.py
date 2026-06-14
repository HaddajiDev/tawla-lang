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


def _router_prog(route_method, route_pattern, handler_body):
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
    src = _router_prog("get", "/users/:id", 'req.respond(200, req.param("id"));')
    assert _serve(tmp_path, src, path="/users/42") == (200, "42")


def test_multi_param(tmp_path):
    src = _router_prog("get", "/a/:x/b/:y",
                       'req.respond(200, req.param("x") + "-" + req.param("y"));')
    assert _serve(tmp_path, src, path="/a/1/b/2") == (200, "1-2")


def test_static_mismatch_404(tmp_path):
    src = _router_prog("get", "/users/:id", 'req.respond(200, "x");')
    assert _serve(tmp_path, src, path="/accounts/5")[0] == 404


def test_segment_count_mismatch_404(tmp_path):
    src = _router_prog("get", "/users/:id", 'req.respond(200, "x");')
    assert _serve(tmp_path, src, path="/users/5/extra")[0] == 404


def test_method_mismatch_404(tmp_path):
    src = _router_prog("get", "/users/:id", 'req.respond(200, "x");')
    assert _serve(tmp_path, src, method="POST", path="/users/5", body="")[0] == 404


def test_query_present_and_path_clean(tmp_path):
    src = _router_prog("get", "/search",
                       'req.respond(200, req.query("q") + "|" + req.path());')
    assert _serve(tmp_path, src, path="/search?q=hi&page=2") == (200, "hi|/search")


def test_query_absent_is_null(tmp_path):
    src = _router_prog("get", "/search",
                       'string v = req.query("nope"); '
                       'if (v == null) { req.respond(200, "NULL"); } else { req.respond(200, v); }')
    assert _serve(tmp_path, src, path="/search") == (200, "NULL")


def test_header_case_insensitive(tmp_path):
    src = _router_prog("get", "/h", 'req.respond(200, req.header("x-test"));')
    assert _serve(tmp_path, src, path="/h", headers={"X-Test": "hello"}) == (200, "hello")
