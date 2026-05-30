"""M17: string operations — length, equality, concatenation."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError


def test_string_length(run_twl):
    assert run_twl('print("hello".length);').stdout == "5\n"


def test_empty_string_length(run_twl):
    assert run_twl('string s = ""; print(s.length);').stdout == "0\n"


def test_concatenation(run_twl):
    assert run_twl('print("Hello, " + "Tawla!");').stdout == "Hello, Tawla!\n"


def test_concatenation_of_variables(run_twl):
    src = 'string a = "foo"; string b = "bar"; string c = a + b; print(c); print(c.length);'
    assert run_twl(src).stdout == "foobar\n6\n"


def test_equality_true(run_twl):
    assert run_twl('print("abc" == "abc");').stdout == "1\n"


def test_equality_false(run_twl):
    assert run_twl('print("abc" == "abd");').stdout == "0\n"


def test_inequality(run_twl):
    assert run_twl('print("abc" != "xyz");').stdout == "1\n"


def test_string_compare_in_if(run_twl):
    src = 'string s = "yes"; if (s == "yes") { print(1); } else { print(0); }'
    assert run_twl(src).stdout == "1\n"


def test_length_is_read_only():
    with pytest.raises(SemaError):
        run_source('string s = "x"; s.length = 9;')
