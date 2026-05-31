"""M23: predefined math functions (sqrt, abs, min, max, pow, floor, ceil)."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError


def test_sqrt(run_twl):
    assert run_twl("class Main { void main() { print(sqrt(16.0)); } }").stdout == "4\n"


def test_sqrt_widens_int_arg(run_twl):
    assert run_twl("class Main { void main() { print(sqrt(9)); } }").stdout == "3\n"


def test_pow(run_twl):
    assert run_twl("class Main { void main() { print(pow(2.0, 10.0)); } }").stdout == "1024\n"


def test_abs_int_returns_int(run_twl):
    src = "class Main { void main() { print(abs(-5)); print(abs(5)); } }"
    assert run_twl(src).stdout == "5\n5\n"


def test_abs_float_returns_float(run_twl):
    assert run_twl("class Main { void main() { print(abs(-3.5)); } }").stdout == "3.5\n"


def test_min_max_int(run_twl):
    src = "class Main { void main() { print(min(3, 7)); print(max(3, 7)); } }"
    assert run_twl(src).stdout == "3\n7\n"


def test_min_max_float(run_twl):
    src = "class Main { void main() { print(min(2.5, 1.5)); print(max(2.5, 1.5)); } }"
    assert run_twl(src).stdout == "1.5\n2.5\n"


def test_min_mixed_promotes(run_twl):
    assert run_twl("class Main { void main() { print(max(3, 2.5)); } }").stdout == "3\n"


def test_floor_and_ceil(run_twl):
    src = "class Main { void main() { print(floor(3.9)); print(ceil(3.1)); } }"
    assert run_twl(src).stdout == "3\n4\n"


def test_abs_in_expression(run_twl):
    src = "class Main { void main() { int d = abs(3 - 10); print(d); } }"
    assert run_twl(src).stdout == "7\n"


def test_user_function_shadows_builtin(run_twl):
    """A user-defined function with a builtin's name takes precedence."""
    src = (
        "int abs(int x) { return 42; }"
        " class Main { void main() { print(abs(-5)); } }"
    )
    assert run_twl(src).stdout == "42\n"


def test_wrong_arity_is_error():
    with pytest.raises(SemaError):
        run_source("class Main { void main() { print(sqrt(1.0, 2.0)); } }")


def test_non_numeric_arg_is_error():
    with pytest.raises(SemaError):
        run_source('class Main { void main() { print(sqrt("hi")); } }')
