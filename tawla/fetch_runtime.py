"""Outbound HTTP client for Tawla's fetch / httpRequest, hosted in Python and
handed to the JIT via llvmlite's add_symbol (like http_runtime / io_runtime).

A blocking request via urllib; the status code and body are stored and read back
through the __fetch_status / __fetch_body primitives. Network failures surface as
status 0 with an empty body rather than raising.
"""

import ctypes
import urllib.error
import urllib.request

import llvmlite.binding as llvm

from .gc_runtime import HEAP


class FetchState:
    def __init__(self):
        self.responses: dict = {}
        self._next = 1

    def reset(self) -> None:
        self.responses.clear()
        self._next = 1

    def fetch(self, method: str, url: str, body: str) -> int:
        data = body.encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
                text = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                text = e.read().decode("utf-8", "replace")
            except Exception:
                text = ""
        except Exception:
            status = 0
            text = ""
        rid = self._next
        self._next += 1
        self.responses[rid] = (status, text)
        return rid

    def status(self, rid: int) -> int:
        return self.responses[rid][0]

    def body(self, rid: int) -> str:
        return self.responses[rid][1]


STATE = FetchState()


def _alloc(s: str) -> int:
    data = s.encode("utf-8") + b"\x00"
    addr = HEAP.alloc(len(data))
    ctypes.memmove(addr, data, len(data))
    return addr


_c_fetch = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p)(
    lambda m, u, b: STATE.fetch(
        m.decode("utf-8") if m else "GET",
        u.decode("utf-8") if u else "",
        b.decode("utf-8") if b else "",
    )
)
_c_status = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32)(lambda r: STATE.status(r))
_c_body = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int32)(lambda r: _alloc(STATE.body(r)))

_CALLBACKS = [_c_fetch, _c_status, _c_body]
_registered = False


def install() -> None:
    """Register the fetch primitives with llvmlite, then clear state for a run."""
    global _registered
    if not _registered:
        cast = ctypes.cast
        llvm.add_symbol("__fetch", cast(_c_fetch, ctypes.c_void_p).value)
        llvm.add_symbol("__fetch_status", cast(_c_status, ctypes.c_void_p).value)
        llvm.add_symbol("__fetch_body", cast(_c_body, ctypes.c_void_p).value)
        _registered = True
    STATE.reset()
