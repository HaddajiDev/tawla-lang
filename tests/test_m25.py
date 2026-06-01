"""M25: null and default-initialized variables."""

import pytest

from tawla.ast_nodes import NullLiteral, PrintStmt
from tawla.lexer import tokenize
from tawla.parser import parse
from tawla.tokens import TokenKind


def test_null_lexes_as_keyword():
    assert tokenize("null")[0].kind is TokenKind.KW_NULL


def test_null_parses_to_null_literal():
    items = parse(tokenize("print(null);"))
    assert isinstance(items[0], PrintStmt)
    assert isinstance(items[0].expr, NullLiteral)
