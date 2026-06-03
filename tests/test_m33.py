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
        'Json o = jsonObject(); o.setInt("n", 42);'
        ' Json back = parseJson(o.toString()); print(back.get("n").asInt());'
    )
    assert run_twl(src).stdout == "42\n"


def test_escaping_round_trip(run_twl):
    src = _main(
        'Json o = jsonObject(); o.setString("k", "a\\"b\\nc");'
        ' Json back = parseJson(o.toString());'
        ' print(back.get("k").asString().length);'
    )
    assert run_twl(src).stdout == "5\n"


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
