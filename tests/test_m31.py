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


def test_to_int(run_twl):
    assert run_twl(_main('print(toInt("42")); print(toInt("-7"));')).stdout == "42\n-7\n"


def test_to_int_non_numeric_is_zero(run_twl):
    assert run_twl(_main('print(toInt("xyz"));')).stdout == "0\n"


def test_to_float(run_twl):
    assert run_twl(_main('print(toFloat("3.5"));')).stdout == "3.5\n"


def test_to_string_int(run_twl):
    assert run_twl(_main('print(toString(42));')).stdout == "42\n"


def test_to_string_float(run_twl):
    assert run_twl(_main('print(toString(3.5));')).stdout == "3.5\n"


def test_round_trip(run_twl):
    assert run_twl(_main('print(toInt(toString(123)));')).stdout == "123\n"


def test_to_string_accepts_string_and_bool():
    # toString is a universal stringifier: string -> itself, bool -> true/false.
    run_source('class Main { void main() { string s = toString("x"); string b = toString(true); } }')


def test_to_int_requires_string():
    with pytest.raises(SemaError):
        run_source("class Main { void main() { int n = toInt(5); } }")
