"""M5: the sema stage — type checking, the bool type, and `var` inference."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError


# --- type errors are rejected before codegen --------------------------------

@pytest.mark.parametrize(
    "src",
    [
        "int x = true;",                 # int <- bool
        "bool b = 1;",                   # bool <- int
        "int x = 1 + true;",             # arithmetic on bool
        "int x = -true;",                # unary minus on bool
        "if (1) { print(1); }",          # condition not bool
        "while (5) { print(1); }",       # condition not bool
        "int x = 1; x = true;",          # reassign wrong type
        "int x = (1 < 2);",              # int <- bool comparison result
        "int x = 1 == true;",            # mismatched == operands
        "bool f() { return 5; }",        # return type mismatch
        "int f(int a) { return a; } print(f(true));",  # arg type mismatch
    ],
)
def test_type_errors_rejected(src):
    with pytest.raises(SemaError):
        run_source(src)


# --- well-typed programs run -------------------------------------------------

def test_bool_variable(run_twl):
    assert run_twl("bool b = true; print(b);").stdout == "1\n"


def test_bool_from_comparison(run_twl):
    assert run_twl("bool b = 3 < 5; print(b);").stdout == "1\n"


def test_bool_returning_function(run_twl):
    src = "bool positive(int n) { return n > 0; } print(positive(7));"
    assert run_twl(src).stdout == "1\n"


def test_bool_equality(run_twl):
    assert run_twl("bool b = (true == false); print(b);").stdout == "0\n"


# --- var inference -----------------------------------------------------------

def test_var_infers_int(run_twl):
    assert run_twl("var x = 41; x = x + 1; print(x);").stdout == "42\n"


def test_var_infers_bool(run_twl):
    assert run_twl("var b = 2 < 1; print(b);").stdout == "0\n"


def test_var_inferred_type_is_enforced():
    # x is inferred int, so assigning a bool must fail.
    with pytest.raises(SemaError):
        run_source("var x = 5; x = true;")
