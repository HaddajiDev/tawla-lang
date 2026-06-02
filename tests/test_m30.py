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
