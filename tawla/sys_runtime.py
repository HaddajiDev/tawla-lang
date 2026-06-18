"""Backend essentials for Tawla's Sys.twl / Fs.twl / Crypto.twl, hosted in
Python and handed to the JIT via llvmlite's add_symbol (like sqlite_runtime).

File operations return a sentinel and stash the error message; Fs.twl turns a
failure into a Tawla throw (the runtime can't unwind JIT frames itself).
"""

import ctypes
import hashlib
import hmac
import os
import time
import uuid

import llvmlite.binding as llvm

from .gc_runtime import HEAP

_last_fs_error = ""


def _alloc(s):
    data = s.encode("utf-8") + b"\x00"
    addr = HEAP.alloc(len(data))
    ctypes.memmove(addr, data, len(data))
    return addr


def _dec(b):
    return b.decode("utf-8") if b else ""


def _env_get(name):
    v = os.environ.get(name)
    return _alloc(v) if v is not None else 0


def _time_secs():
    return int(time.time())


def _time_millis():
    return time.time() * 1000.0


def _sleep_millis(ms):
    time.sleep(ms / 1000.0)


def _uuid():
    return _alloc(str(uuid.uuid4()))


def _file_read(path):
    global _last_fs_error
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _alloc(f.read())
    except OSError as e:
        _last_fs_error = str(e)
        return 0


def _file_write(path, content):
    global _last_fs_error
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return 0
    except OSError as e:
        _last_fs_error = str(e)
        return 1


def _file_append(path, content):
    global _last_fs_error
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
        return 0
    except OSError as e:
        _last_fs_error = str(e)
        return 1


def _file_exists(path):
    return 1 if os.path.exists(path) else 0


def _fs_error():
    return _alloc(_last_fs_error)


def _sha256(s):
    return _alloc(hashlib.sha256(s.encode("utf-8")).hexdigest())


def _hmac_sha256(key, message):
    return _alloc(
        hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    )


_c_env_get = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p)(lambda n: _env_get(_dec(n)))
_c_time_secs = ctypes.CFUNCTYPE(ctypes.c_int32)(lambda: _time_secs())
_c_time_millis = ctypes.CFUNCTYPE(ctypes.c_double)(lambda: _time_millis())
_c_sleep_millis = ctypes.CFUNCTYPE(None, ctypes.c_int32)(lambda ms: _sleep_millis(ms))
_c_uuid = ctypes.CFUNCTYPE(ctypes.c_void_p)(lambda: _uuid())
_c_file_read = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p)(lambda p: _file_read(_dec(p)))
_c_file_write = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_char_p, ctypes.c_char_p)(
    lambda p, c: _file_write(_dec(p), _dec(c))
)
_c_file_append = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_char_p, ctypes.c_char_p)(
    lambda p, c: _file_append(_dec(p), _dec(c))
)
_c_file_exists = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_char_p)(lambda p: _file_exists(_dec(p)))
_c_fs_error = ctypes.CFUNCTYPE(ctypes.c_void_p)(lambda: _fs_error())
_c_sha256 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p)(lambda s: _sha256(_dec(s)))
_c_hmac_sha256 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p)(
    lambda k, m: _hmac_sha256(_dec(k), _dec(m))
)

_CALLBACKS = [
    _c_env_get, _c_time_secs, _c_time_millis, _c_sleep_millis, _c_uuid,
    _c_file_read, _c_file_write, _c_file_append, _c_file_exists, _c_fs_error,
    _c_sha256, _c_hmac_sha256,
]
_registered = False


def install():
    """Register the essentials primitives with llvmlite, then reset state."""
    global _registered, _last_fs_error
    if not _registered:
        cast = ctypes.cast
        llvm.add_symbol("__env_get", cast(_c_env_get, ctypes.c_void_p).value)
        llvm.add_symbol("__time_secs", cast(_c_time_secs, ctypes.c_void_p).value)
        llvm.add_symbol("__time_millis", cast(_c_time_millis, ctypes.c_void_p).value)
        llvm.add_symbol("__sleep_millis", cast(_c_sleep_millis, ctypes.c_void_p).value)
        llvm.add_symbol("__uuid", cast(_c_uuid, ctypes.c_void_p).value)
        llvm.add_symbol("__file_read", cast(_c_file_read, ctypes.c_void_p).value)
        llvm.add_symbol("__file_write", cast(_c_file_write, ctypes.c_void_p).value)
        llvm.add_symbol("__file_append", cast(_c_file_append, ctypes.c_void_p).value)
        llvm.add_symbol("__file_exists", cast(_c_file_exists, ctypes.c_void_p).value)
        llvm.add_symbol("__fs_error", cast(_c_fs_error, ctypes.c_void_p).value)
        llvm.add_symbol("__sha256", cast(_c_sha256, ctypes.c_void_p).value)
        llvm.add_symbol("__hmac_sha256", cast(_c_hmac_sha256, ctypes.c_void_p).value)
        _registered = True
    _last_fs_error = ""
