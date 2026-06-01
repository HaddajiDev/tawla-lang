"""M13: arrays — allocation, indexing, length, zero-init."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError


def test_array_length(run_twl):
    assert run_twl("int[] a = new int[7]; print(a.length);").stdout == "7\n"


def test_array_zero_initialized(run_twl):
    assert run_twl("int[] a = new int[3]; print(a[0]); print(a[2]);").stdout == "0\n0\n"


def test_index_write_and_read(run_twl):
    assert run_twl("int[] a = new int[3]; a[1] = 42; print(a[1]);").stdout == "42\n"


def test_fill_and_sum(run_twl):
    src = (
        "int[] a = new int[5]; int i = 0; "
        "while (i < a.length) { a[i] = i * i; i = i + 1; } "
        "int s = 0; i = 0; while (i < a.length) { s = s + a[i]; i = i + 1; } print(s);"
    )
    assert run_twl(src).stdout == "30\n"   # 0+1+4+9+16


def test_string_array(run_twl):
    src = 'string[] xs = new string[2]; xs[0] = "hi"; xs[1] = "yo"; print(xs[0]); print(xs[1]);'
    assert run_twl(src).stdout == "hi\nyo\n"


def test_array_of_objects(run_twl):
    src = (
        "class Cell { int v; Cell(int v) { this.v = v; } public int get() { return this.v; } } "
        "Cell[] cs = new Cell[2]; cs[0] = new Cell(10); cs[1] = new Cell(20); "
        "print(cs[0].get()); print(cs[1].get());"
    )
    assert run_twl(src).stdout == "10\n20\n"


def test_dynamic_size(run_twl):
    src = "int n = 4; int[] a = new int[n + 1]; print(a.length);"
    assert run_twl(src).stdout == "5\n"


@pytest.mark.parametrize(
    "src",
    [
        'int[] a = new int["x"];',        # non-int size
        "int x = 5; print(x[0]);",        # indexing a non-array
        "int[] a = new int[2]; bool b = a[0];",  # element type mismatch
        "int[] a = new int[2]; a.length = 9;",   # length is read-only
    ],
)
def test_array_errors(src):
    with pytest.raises(SemaError):
        run_source(src)
