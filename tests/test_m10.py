"""M10: strings — literals, the string type, printing, and storage."""

import pytest

from tawla.compiler import run_source
from tawla.lexer import LexError, tokenize
from tawla.sema import SemaError
from tawla.tokens import TokenKind


def test_lexer_string_literal_with_escapes():
    toks = tokenize(r'"a\tb\n"')
    assert toks[0].kind is TokenKind.STRING
    assert toks[0].text == "a\tb\n"


def test_lexer_unterminated_string():
    with pytest.raises(LexError):
        tokenize('"oops')


def test_print_string_literal(run_twl):
    assert run_twl('print("Hello, Tawla!");').stdout == "Hello, Tawla!\n"


def test_string_variable(run_twl):
    assert run_twl('string s = "hi"; print(s);').stdout == "hi\n"


def test_string_field_and_method(run_twl):
    src = (
        "class Person { string name; Person(string n) { this.name = n; } "
        "public string who() { return this.name; } } "
        'print(new Person("Ada").who());'
    )
    assert run_twl(src).stdout == "Ada\n"


def test_string_through_function(run_twl):
    src = 'string echo(string s) { return s; } print(echo("ping"));'
    assert run_twl(src).stdout == "ping\n"


def test_mixed_int_and_string_print(run_twl):
    assert run_twl('print("n ="); print(42);').stdout == "n =\n42\n"


def test_string_type_errors():
    with pytest.raises(SemaError):
        run_source('int x = "no";')
    with pytest.raises(SemaError):
        run_source('string s = 5;')
