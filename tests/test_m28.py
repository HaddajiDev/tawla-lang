"""M28: logical operators (&&, ||, !)."""

import pytest

from tawla.lexer import LexError, tokenize
from tawla.tokens import TokenKind


def test_lex_and_or_not():
    kinds = [t.kind for t in tokenize("&& || !")]
    assert kinds[:3] == [TokenKind.AND, TokenKind.OR, TokenKind.NOT]


def test_lex_not_equals_still_works():
    assert tokenize("!=")[0].kind is TokenKind.NE


def test_lex_single_ampersand_is_error():
    with pytest.raises(LexError):
        tokenize("a & b")
