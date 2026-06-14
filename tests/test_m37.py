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
