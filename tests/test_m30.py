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
    src = (
        "class Main { void main() {"
        " int s = __http_listen(0); print(__http_port(s));"
        " int r = __http_accept(s); __http_respond(r, 200, __http_path(r)); } }"
    )
    status, body = run_server_once(tmp_path, src, path="/hello")
    assert status == 200
    assert body == "/hello"


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
    ' Router router = new Router(); router.get("/hi", new Hi());'
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


def test_new_expression_statement_parses():
    # `new Foo().method();` is a valid statement (regression for the server example).
    from tawla.ast_nodes import ExprStmt, MethodCall
    from tawla.parser import parse
    from tawla.lexer import tokenize
    stmt = parse(tokenize("new Foo().bar();"))[0]
    assert isinstance(stmt, ExprStmt)
    assert isinstance(stmt.expr, MethodCall)
