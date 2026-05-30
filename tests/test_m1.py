"""M1: lexer + recursive-descent parser + arithmetic codegen.

Lexer/parser checks run in-process. Arithmetic results are observed through a
real `print`, run as a subprocess (see `run_twl` in conftest.py).
"""

import pytest

from tawla.lexer import LexError, tokenize
from tawla.parser import ParseError, parse
from tawla.tokens import TokenKind


def kinds(src):
    return [t.kind for t in tokenize(src)]


def test_lexer_basic():
    assert kinds("1 + 2") == [
        TokenKind.INT, TokenKind.PLUS, TokenKind.INT, TokenKind.EOF
    ]


def test_lexer_rejects_unknown_char():
    with pytest.raises(LexError):
        tokenize("1 $ 2")


def test_lexer_ignores_leading_bom():
    # Some Windows editors prepend a UTF-8 byte-order mark; it must be skipped.
    assert kinds(chr(0xFEFF) + "1 + 2") == [
        TokenKind.INT, TokenKind.PLUS, TokenKind.INT, TokenKind.EOF
    ]


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("42", 42),
        ("1 + 2 + 3", 6),
        ("1 + 2 * 3", 7),       # precedence: * before +
        ("(1 + 2) * 3", 9),     # parentheses override precedence
        ("10 - 2 - 3", 5),      # left associativity
        ("7 / 2", 3),           # signed integer division truncates
        ("-5 + 8", 3),          # unary minus
        ("2 * -3", -6),
        ("-(4 + 1)", -5),
    ],
)
def test_arithmetic(run_twl, expr, expected):
    result = run_twl(f"print({expr});")
    assert result.returncode == 0
    assert result.stdout == f"{expected}\n"


def test_parser_rejects_unbalanced_paren():
    with pytest.raises(ParseError):
        parse(tokenize("print(1 + 2;"))
