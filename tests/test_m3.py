"""M3: comparisons, booleans, if/else, while, reassignment, basic blocks."""

import pytest

from tawla.lexer import tokenize
from tawla.parser import ParseError, parse
from tawla.tokens import TokenKind


def test_lexer_two_char_operators():
    kinds = [t.kind for t in tokenize("<= >= == != < >")]
    assert kinds == [
        TokenKind.LE, TokenKind.GE, TokenKind.EQ, TokenKind.NE,
        TokenKind.LT, TokenKind.GT, TokenKind.EOF,
    ]


def test_lexer_lone_bang_is_error():
    with pytest.raises(Exception):
        tokenize("a ! b")


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("1 < 2", 1),
        ("2 < 1", 0),
        ("3 == 3", 1),
        ("3 != 3", 0),
        ("5 >= 5", 1),
        ("4 <= 3", 0),
        ("true", 1),
        ("false", 0),
    ],
)
def test_comparisons_and_bools(run_twl, expr, expected):
    result = run_twl(f"print({expr});")
    assert result.returncode == 0
    assert result.stdout == f"{expected}\n"


def test_if_true_branch(run_twl):
    assert run_twl("if (1 < 2) { print(10); } else { print(20); }").stdout == "10\n"


def test_if_false_branch(run_twl):
    assert run_twl("if (2 < 1) { print(10); } else { print(20); }").stdout == "20\n"


def test_if_without_else_skips(run_twl):
    assert run_twl("print(1); if (false) { print(99); } print(2);").stdout == "1\n2\n"


def test_else_if_chain(run_twl):
    src = "int x = 7; if (x > 10) { print(100); } else if (x > 5) { print(50); } else { print(0); }"
    assert run_twl(src).stdout == "50\n"


def test_while_sum_1_to_10(run_twl):
    src = "int sum = 0; int i = 1; while (i <= 10) { sum = sum + i; i = i + 1; } print(sum);"
    assert run_twl(src).stdout == "55\n"


def test_while_never_runs(run_twl):
    assert run_twl("while (false) { print(99); } print(7);").stdout == "7\n"


def test_reassignment(run_twl):
    assert run_twl("int x = 1; x = x + 41; print(x);").stdout == "42\n"


def test_assign_to_undefined_is_error():
    # parses fine; fails in sema (no such variable)
    from tawla.compiler import run_source
    from tawla.sema import SemaError

    with pytest.raises(SemaError):
        run_source("y = 5;")


def test_missing_brace_is_parse_error():
    with pytest.raises(ParseError):
        parse(tokenize("if (1 < 2) { print(1);"))
