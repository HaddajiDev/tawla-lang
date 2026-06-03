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
_c_respond = ctypes.CFUNCTYPE(None, ctypes.c_int32, ctypes.c_int32, ctypes.c_char_p, ctypes.c_char_p)(
    lambda r, st, ct, b: STATE.respond(
        r, st, ct.decode("utf-8") if ct else "text/plain", b.decode("utf-8") if b else ""
    )
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
