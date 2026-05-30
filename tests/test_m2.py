"""M2: statements, variable declarations, the symbol table, and print.

Output is checked via subprocess (`run_twl`); compile-time errors are raised
in-process before any I/O, so those are checked directly.
"""

import pytest

from tawla.compiler import run_source
from tawla.lexer import tokenize
from tawla.parser import ParseError, parse
from tawla.sema import SemaError


def test_declare_and_print(run_twl):
    result = run_twl("int x = 5; print(x * 2);")
    assert result.returncode == 0
    assert result.stdout == "10\n"


def test_multiple_statements_run_in_order(run_twl):
    result = run_twl("int a = 1; print(a); int b = a + 9; print(b);")
    assert result.stdout == "1\n10\n"


def test_variable_references_another(run_twl):
    result = run_twl("int a = 4; int b = a + a; print(b);")
    assert result.stdout == "8\n"


def test_undefined_variable_is_an_error():
    with pytest.raises(SemaError):
        run_source("print(y);")


def test_redeclaration_is_an_error():
    with pytest.raises(SemaError):
        run_source("int x = 1; int x = 2;")


def test_missing_semicolon_is_a_parse_error():
    with pytest.raises(ParseError):
        parse(tokenize("int x = 5 print(x);"))
