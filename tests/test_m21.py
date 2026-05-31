"""M21: C-style for loops."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError


def test_basic_for(run_twl):
    src = (
        "class Main { void main() {"
        " int s = 0; for (int i = 1; i <= 5; i = i + 1) { s = s + i; } print(s); } }"
    )
    assert run_twl(src).stdout == "15\n"


def test_for_counts_down(run_twl):
    src = (
        "class Main { void main() {"
        " for (int i = 3; i > 0; i = i - 1) { print(i); } } }"
    )
    assert run_twl(src).stdout == "3\n2\n1\n"


def test_nested_for(run_twl):
    src = (
        "class Main { void main() {"
        " int n = 0;"
        " for (int i = 0; i < 3; i = i + 1) {"
        "   for (int j = 0; j < 3; j = j + 1) { n = n + 1; } }"
        " print(n); } }"
    )
    assert run_twl(src).stdout == "9\n"


def test_two_loops_reuse_variable(run_twl):
    """The loop variable is scoped to the loop, so `i` can be reused."""
    src = (
        "class Main { void main() {"
        " int a = 0; for (int i = 0; i < 3; i = i + 1) { a = a + 1; }"
        " int b = 0; for (int i = 0; i < 5; i = i + 1) { b = b + 1; }"
        " print(a); print(b); } }"
    )
    assert run_twl(src).stdout == "3\n5\n"


def test_for_with_external_counter(run_twl):
    """init and step can use an already-declared variable."""
    src = (
        "class Main { void main() {"
        " int i = 0; int s = 0; for (; i < 4; i = i + 1) { s = s + i; } print(s); } }"
    )
    assert run_twl(src).stdout == "6\n"


def test_for_no_condition_with_break_via_return(run_twl):
    src = (
        "int firstOver(int limit) {"
        " for (int i = 0; ; i = i + 1) { if (i > limit) { return i; } } return 0; }"
        " class Main { void main() { print(firstOver(5)); } }"
    )
    assert run_twl(src).stdout == "6\n"


def test_loop_variable_not_visible_after(run_twl):
    src = (
        "class Main { void main() {"
        " for (int i = 0; i < 3; i = i + 1) { print(i); } print(i); } }"
    )
    result = run_twl(src)
    assert result.returncode != 0
    assert "i" in result.stderr


def test_for_condition_must_be_bool():
    src = "class Main { void main() { for (int i = 0; i; i = i + 1) {} } }"
    with pytest.raises(SemaError):
        run_source(src)
