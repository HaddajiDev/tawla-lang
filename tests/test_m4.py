"""M4: function declarations, parameters, returns, calls, and scopes."""

import pytest

from tawla.compiler import run_source
from tawla.lexer import tokenize
from tawla.parser import parse
from tawla.sema import SemaError


def test_simple_function(run_twl):
    src = "int add(int a, int b) { return a + b; } print(add(3, 4));"
    assert run_twl(src).stdout == "7\n"


def test_no_param_function(run_twl):
    assert run_twl("int answer() { return 42; } print(answer());").stdout == "42\n"


def test_recursion_factorial(run_twl):
    src = "int f(int n) { if (n <= 1) { return 1; } return n * f(n - 1); } print(f(5));"
    assert run_twl(src).stdout == "120\n"


@pytest.mark.parametrize("n, expected", [(0, 1), (1, 1), (3, 6), (6, 720)])
def test_factorial_values(run_twl, n, expected):
    src = f"int f(int n) {{ if (n <= 1) {{ return 1; }} return n * f(n - 1); }} print(f({n}));"
    assert run_twl(src).stdout == f"{expected}\n"


def test_function_uses_local_variable(run_twl):
    src = "int sq(int x) { int r = x * x; return r; } print(sq(9));"
    assert run_twl(src).stdout == "81\n"


def test_functions_can_call_each_other(run_twl):
    src = (
        "int dbl(int x) { return x * 2; } "
        "int quad(int x) { return dbl(dbl(x)); } "
        "print(quad(5));"
    )
    assert run_twl(src).stdout == "20\n"


def test_scope_is_isolated_per_function():
    # `a` is a parameter of f; g cannot see it.
    src = "int f(int a) { return a; } int g() { return a; } print(g());"
    with pytest.raises(SemaError):
        run_source(src)


def test_call_to_undefined_function_is_error():
    with pytest.raises(SemaError):
        run_source("print(nope(1));")


def test_arity_mismatch_is_error():
    with pytest.raises(SemaError):
        run_source("int f(int a) { return a; } print(f(1, 2));")


def test_duplicate_function_is_error():
    with pytest.raises(SemaError):
        run_source("int f() { return 1; } int f() { return 2; }")


def test_function_decl_vs_var_decl_disambiguation():
    # `int x = ...` is a var decl, `int x(...)` is a function decl.
    items = parse(tokenize("int x = 5; int f() { return x; }"))
    from tawla.ast_nodes import FuncDecl, VarDecl
    assert isinstance(items[0], VarDecl)
    assert isinstance(items[1], FuncDecl)
