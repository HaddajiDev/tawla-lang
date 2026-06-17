"""SQLite for Tawla's Sql.twl, hosted in Python and handed to the JIT via
llvmlite's add_symbol (like fetch_runtime).

Fallible operations return a status code and stash the error message; Sql.twl
checks the status and does `throw __sql_error()`, turning a Python-side failure
into a catchable Tawla exception (the runtime cannot unwind JIT frames itself).
"""

import ctypes
import sqlite3

import llvmlite.binding as llvm

from .gc_runtime import HEAP


class SqlState:
    def __init__(self):
        self.conns = {}
        self.stmts = {}   # sid -> [conn_id, sql, params]
        self.rsets = {}   # rid -> {"data": list, "cols": dict, "pos": int}
        self._next = 1
        self.err = ""

    def reset(self):
        for c in self.conns.values():
            try:
                c.close()
            except Exception:
                pass
        self.conns.clear()
        self.stmts.clear()
        self.rsets.clear()
        self._next = 1
        self.err = ""

    def _id(self):
        i = self._next
        self._next += 1
        return i

    def open(self, path):
        try:
            conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
            cid = self._id()
            self.conns[cid] = conn
            return cid
        except Exception as e:
            self.err = str(e)
            return -1

    def prepare(self, cid, sql):
        sid = self._id()
        self.stmts[sid] = [cid, sql, []]
        return sid

    def _bind(self, sid, index, value):
        params = self.stmts[sid][2]
        while len(params) <= index:
            params.append(None)
        params[index] = value

    def bind_int(self, sid, index, value):
        self._bind(sid, index, value)

    def bind_float(self, sid, index, value):
        self._bind(sid, index, value)

    def bind_str(self, sid, index, value):
        self._bind(sid, index, value)

    def exec(self, sid):
        cid, sql, params = self.stmts[sid]
        try:
            self.conns[cid].execute(sql, params)
            return 0
        except Exception as e:
            self.err = str(e)
            return 1

    def query(self, sid):
        cid, sql, params = self.stmts[sid]
        try:
            cur = self.conns[cid].execute(sql, params)
            data = cur.fetchall()
            cols = {d[0]: idx for idx, d in enumerate(cur.description or [])}
            rid = self._id()
            self.rsets[rid] = {"data": data, "cols": cols, "pos": -1}
            return rid
        except Exception as e:
            self.err = str(e)
            return -1

    def next(self, rid):
        rs = self.rsets[rid]
        rs["pos"] += 1
        return 1 if rs["pos"] < len(rs["data"]) else 0

    def _cell(self, rid, i):
        rs = self.rsets[rid]
        return rs["data"][rs["pos"]][i]

    def col_index(self, rid, name):
        return self.rsets[rid]["cols"].get(name, -1)

    def col_int(self, rid, i):
        v = self._cell(rid, i)
        if v is None:
            return 0
        try:
            return int(v)
        except (ValueError, TypeError):
            return 0

    def col_float(self, rid, i):
        v = self._cell(rid, i)
        if v is None:
            return 0.0
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.0

    def col_str(self, rid, i):
        v = self._cell(rid, i)
        return None if v is None else str(v)

    def is_null(self, rid, i):
        return 1 if self._cell(rid, i) is None else 0

    def error(self):
        return self.err


STATE = SqlState()


def _alloc(s):
    data = s.encode("utf-8") + b"\x00"
    addr = HEAP.alloc(len(data))
    ctypes.memmove(addr, data, len(data))
    return addr


def _alloc_or_null(s):
    return _alloc(s) if s is not None else 0


def _dec(b):
    return b.decode("utf-8") if b else ""


_c_open = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_char_p)(lambda p: STATE.open(_dec(p)))
_c_prepare = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32, ctypes.c_char_p)(
    lambda c, s: STATE.prepare(c, _dec(s))
)
_c_bind_int = ctypes.CFUNCTYPE(None, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32)(
    lambda s, i, v: STATE.bind_int(s, i, v)
)
_c_bind_float = ctypes.CFUNCTYPE(None, ctypes.c_int32, ctypes.c_int32, ctypes.c_double)(
    lambda s, i, v: STATE.bind_float(s, i, v)
)
_c_bind_str = ctypes.CFUNCTYPE(None, ctypes.c_int32, ctypes.c_int32, ctypes.c_char_p)(
    lambda s, i, v: STATE.bind_str(s, i, _dec(v))
)
_c_exec = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32)(lambda s: STATE.exec(s))
_c_query = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32)(lambda s: STATE.query(s))
_c_next = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32)(lambda r: STATE.next(r))
_c_col_index = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32, ctypes.c_char_p)(
    lambda r, n: STATE.col_index(r, _dec(n))
)
_c_col_int = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32, ctypes.c_int32)(
    lambda r, i: STATE.col_int(r, i)
)
_c_col_float = ctypes.CFUNCTYPE(ctypes.c_double, ctypes.c_int32, ctypes.c_int32)(
    lambda r, i: STATE.col_float(r, i)
)
_c_col_str = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32)(
    lambda r, i: _alloc_or_null(STATE.col_str(r, i))
)
_c_is_null = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32, ctypes.c_int32)(
    lambda r, i: STATE.is_null(r, i)
)
_c_error = ctypes.CFUNCTYPE(ctypes.c_void_p)(lambda: _alloc(STATE.error()))

_CALLBACKS = [
    _c_open, _c_prepare, _c_bind_int, _c_bind_float, _c_bind_str, _c_exec, _c_query,
    _c_next, _c_col_index, _c_col_int, _c_col_float, _c_col_str, _c_is_null, _c_error,
]
_registered = False


def install():
    """Register the SQLite primitives with llvmlite, then clear state for a run."""
    global _registered
    if not _registered:
        cast = ctypes.cast
        llvm.add_symbol("__sql_open", cast(_c_open, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_prepare", cast(_c_prepare, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_bind_int", cast(_c_bind_int, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_bind_float", cast(_c_bind_float, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_bind_str", cast(_c_bind_str, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_exec", cast(_c_exec, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_query", cast(_c_query, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_next", cast(_c_next, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_col_index", cast(_c_col_index, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_col_int", cast(_c_col_int, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_col_float", cast(_c_col_float, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_col_str", cast(_c_col_str, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_is_null", cast(_c_is_null, ctypes.c_void_p).value)
        llvm.add_symbol("__sql_error", cast(_c_error, ctypes.c_void_p).value)
        _registered = True
    STATE.reset()
