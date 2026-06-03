"""M34: fetch (outbound HTTP client)."""

import http.server
import threading

import pytest


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, body):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/hello":
            self._send(200, "world")
        elif self.path == "/json":
            self._send(200, '{"name":"ada"}')
        else:
            self._send(404, "nope")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n).decode("utf-8")
        self._send(200, body)


@pytest.fixture
def http_server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield port
    finally:
        srv.shutdown()


def test_raw_fetch_get(run_twl, http_server):
    src = (
        "class Main { void main() {"
        f' int r = __fetch("GET", "http://127.0.0.1:{http_server}/hello", "");'
        " print(__fetch_status(r)); print(__fetch_body(r)); } }"
    )
    assert run_twl(src).stdout == "200\nworld\n"


def _main(body):
    return 'import "Http.twl"; class Main { void main() { ' + body + " } }"


def test_fetch_get(run_twl, http_server):
    src = _main(
        f'Response r = fetch("http://127.0.0.1:{http_server}/hello");'
        " print(r.status()); print(r.body());"
    )
    assert run_twl(src).stdout == "200\nworld\n"


def test_fetch_not_found(run_twl, http_server):
    src = _main(
        f'Response r = fetch("http://127.0.0.1:{http_server}/missing"); print(r.status());'
    )
    assert run_twl(src).stdout == "404\n"


def test_http_request_post(run_twl, http_server):
    src = _main(
        f'Response r = httpRequest("POST", "http://127.0.0.1:{http_server}/echo", "payload");'
        " print(r.status()); print(r.body());"
    )
    assert run_twl(src).stdout == "200\npayload\n"


def test_fetch_json_round_trip(run_twl, http_server):
    src = (
        'import "Http.twl"; import "Json.twl";'
        " class Main { void main() {"
        f' Response r = fetch("http://127.0.0.1:{http_server}/json");'
        ' Json d = parseJson(r.body()); print(d.get("name").asString()); } }'
    )
    assert run_twl(src).stdout == "ada\n"


def test_fetch_connection_refused(run_twl):
    src = _main('Response r = fetch("http://127.0.0.1:1/"); print(r.status());')
    assert run_twl(src).stdout == "0\n"
