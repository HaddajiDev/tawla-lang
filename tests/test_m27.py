"""M27: collections (List / Map) and the panic builtin."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError


def _err(result):
    return result.stdout + result.stderr


def test_panic_aborts(run_twl):
    src = 'class Main { void main() { print(1); panic("boom"); print(2); } }'
    r = run_twl(src)
    assert r.returncode != 0
    assert "boom" in _err(r)
    assert "1\n" in r.stdout       # ran before the panic
    assert "2" not in r.stdout     # never reached


def test_panic_wrong_arg_type_is_error():
    with pytest.raises(SemaError):
        run_source("panic(5);")
