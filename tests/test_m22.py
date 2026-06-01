"""M22: floating-point numbers (float / double)."""

import pytest

from tawla.compiler import run_source
from tawla.lexer import tokenize
from tawla.sema import SemaError
from tawla.tokens import TokenKind


def test_float_literal_lexes():
    kinds = [t.kind for t in tokenize("3.14")]
    assert kinds[0] is TokenKind.FLOAT


def test_trailing_dot_is_not_a_float():
    # `5.foo` is INT then DOT, not a malformed float
    kinds = [t.kind for t in tokenize("5.x")]
    assert kinds[0] is TokenKind.INT
    assert kinds[1] is TokenKind.DOT


def test_print_float(run_twl):
    src = 'class Main { void main() { float x = 3.14; print(x); } }'
    assert run_twl(src).stdout == "3.14\n"


def test_double_is_alias_for_float(run_twl):
    src = 'class Main { void main() { double x = 1.5; float y = x; print(y); } }'
    assert run_twl(src).stdout == "1.5\n"


def test_float_arithmetic(run_twl):
    src = 'class Main { void main() { print(1.5 + 2.5); print(2.0 * 3.0); } }'
    assert run_twl(src).stdout == "4\n6\n"


def test_int_promotes_in_mixed_arithmetic(run_twl):
    src = 'class Main { void main() { print(7.0 / 2); print(1 + 0.5); } }'
    assert run_twl(src).stdout == "3.5\n1.5\n"


def test_int_division_stays_integer(run_twl):
    src = 'class Main { void main() { print(7 / 2); } }'
    assert run_twl(src).stdout == "3\n"


def test_int_widens_to_float_on_assignment(run_twl):
    src = 'class Main { void main() { float x = 5; print(x); } }'
    assert run_twl(src).stdout == "5\n"


def test_negate_float(run_twl):
    src = 'class Main { void main() { float x = 3.5; print(-x); } }'
    assert run_twl(src).stdout == "-3.5\n"


def test_float_comparison(run_twl):
    src = (
        "class Main { void main() {"
        " if (3.14 > 3.0) { print(1); } if (1.0 < 0.5) { print(2); } else { print(3); } } }"
    )
    assert run_twl(src).stdout == "1\n3\n"


def test_float_param_and_return(run_twl):
    src = (
        "float half(float x) { return x / 2.0; }"
        " class Main { void main() { print(half(5.0)); } }"
    )
    assert run_twl(src).stdout == "2.5\n"


def test_float_field(run_twl):
    src = (
        "class Circle { float r; Circle(float radius) { this.r = radius; }"
        " public float area() { return 3.14 * this.r * this.r; } }"
        " class Main { void main() { Circle c = new Circle(2.0); print(c.area()); } }"
    )
    assert run_twl(src).stdout == "12.56\n"


def test_float_array(run_twl):
    src = (
        "class Main { void main() {"
        " float[] a = new float[3]; a[0] = 1.5; a[1] = 2.5;"
        " print(a[0] + a[1]); print(a[2]); } }"
    )
    assert run_twl(src).stdout == "4\n0\n"


def test_var_infers_float(run_twl):
    src = 'class Main { void main() { var x = 2.5; print(x + x); } }'
    assert run_twl(src).stdout == "5\n"


def test_cannot_assign_float_to_int():
    with pytest.raises(SemaError):
        run_source("int x = 3.14;")


def test_cannot_pass_float_where_int_expected():
    src = "int f(int n) { return n; } class Main { void main() { print(f(1.5)); } }"
    with pytest.raises(SemaError):
        run_source(src)
