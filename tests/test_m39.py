"""M39: backend essentials (Sys.twl / Fs.twl / Crypto.twl)."""

import ctypes
import hashlib
import hmac


def test_sys_runtime_functions(tmp_path):
    from tawla import sys_runtime as S

    assert S._time_secs() > 1_700_000_000
    assert S._time_millis() > 1_700_000_000_000.0

    u = ctypes.string_at(S._uuid()).decode()
    assert len(u) == 36 and "-" in u

    assert ctypes.string_at(S._sha256("abc")).decode() == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    expect = hmac.new(b"key", b"msg", hashlib.sha256).hexdigest()
    assert ctypes.string_at(S._hmac_sha256("key", "msg")).decode() == expect

    p = str(tmp_path / "f.txt")
    assert S._file_write(p, "hello") == 0
    assert S._file_append(p, " world") == 0
    assert ctypes.string_at(S._file_read(p)).decode() == "hello world"
    assert S._file_exists(p) == 1
    assert S._file_exists(str(tmp_path / "missing")) == 0
    assert S._file_read(str(tmp_path / "missing")) == 0   # error -> null
    assert S._fs_error() != 0                              # message stashed

    import os
    os.environ["TAWLA_TEST_VAR"] = "xyz"
    assert ctypes.string_at(S._env_get("TAWLA_TEST_VAR")).decode() == "xyz"
    assert S._env_get("TAWLA_DEFINITELY_UNSET_VAR_123") == 0


def test_sys_builtins_end_to_end(run_twl):
    src = (
        "class Main { void main() {"
        ' print(__sha256("abc"));'
        ' print(__file_exists("definitely_missing_xyz"));'
        " } }"
    )
    assert run_twl(src).stdout == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n0\n"
    )


def test_sys_getenv(run_twl, monkeypatch):
    monkeypatch.setenv("TAWLA_TEST_ENV", "hello")
    src = 'import "Sys.twl"; class Main { void main() { print(getenv("TAWLA_TEST_ENV")); } }'
    assert run_twl(src).stdout == "hello\n"


def test_sys_getenv_absent(run_twl):
    src = (
        'import "Sys.twl"; class Main { void main() {'
        ' string v = getenv("TAWLA_UNSET_XYZ_123");'
        ' if (v == null) { print("null"); } } }'
    )
    assert run_twl(src).stdout == "null\n"


def test_sys_uuid_and_time(run_twl):
    src = (
        'import "Sys.twl"; class Main { void main() {'
        " string u = uuid(); print(u.length);"
        ' int t = now(); if (t > 1700000000) { print("ok"); }'
        ' float m = nowMillis(); if (m > 1700000000000.0) { print("big"); }'
        ' sleepMillis(10); print("slept"); } }'
    )
    assert run_twl(src).stdout == "36\nok\nbig\nslept\n"


def test_fs_roundtrip(run_twl, tmp_path):
    p = str(tmp_path / "data.txt").replace("\\", "/")
    body = (
        f'writeFile("{p}", "abc"); appendFile("{p}", "def");'
        f' print(readFile("{p}"));'
        f' if (exists("{p}")) {{ print("yes"); }}'
    )
    src = 'import "Fs.twl"; class Main { void main() { ' + body + " } }"
    assert run_twl(src).stdout == "abcdef\nyes\n"


def test_fs_read_error_is_catchable(run_twl, tmp_path):
    p = str(tmp_path / "missing.txt").replace("\\", "/")
    body = (
        f'fuck_around {{ readFile("{p}"); print("ran"); }}'
        ' find_out (e) { print("caught"); }'
    )
    src = 'import "Fs.twl"; class Main { void main() { ' + body + " } }"
    assert run_twl(src).stdout == "caught\n"


def test_crypto(run_twl):
    import hashlib
    import hmac as _hmac
    expect = _hmac.new(b"key", b"msg", hashlib.sha256).hexdigest()
    src = (
        'import "Crypto.twl"; class Main { void main() {'
        ' print(sha256("abc")); print(hmacSha256("key", "msg")); } }'
    )
    out = run_twl(src).stdout
    assert out == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n" + expect + "\n"
    )
