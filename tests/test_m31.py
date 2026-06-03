"""M31: string utilities (charAt, substring, toInt, toFloat, toString)."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError


def _err(result):
    return result.stdout + result.stderr


def _main(body):
    return "class Main { void main() { " + body + " } }"


def test_char_at(run_twl):
    assert run_twl(_main('print(charAt("abc", 0)); print(charAt("abc", 2));')).stdout == "97\n99\n"


def test_char_at_out_of_range_aborts(run_twl):
    r = run_twl(_main('print(charAt("abc", 5));'))
    assert r.returncode != 0
    assert "out of range" in _err(r)


def test_substring(run_twl):
    assert run_twl(_main('print(substring("hello", 1, 4));')).stdout == "ell\n"


def test_substring_empty(run_twl):
    assert run_twl(_main('print(substring("hi", 0, 0));')).stdout == "\n"


def test_substring_full(run_twl):
    assert run_twl(_main('print(substring("hi", 0, 2));')).stdout == "hi\n"


def test_substring_out_of_range_aborts(run_twl):
    r = run_twl(_main('print(substring("hi", 0, 9));'))
    assert r.returncode != 0
    assert "out of range" in _err(r)
