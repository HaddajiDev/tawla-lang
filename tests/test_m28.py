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


from tawla.ast_nodes import BinaryOp, PrintStmt, UnaryOp
from tawla.parser import parse


def _expr(src):
    stmt = parse(tokenize("print(" + src + ");"))[0]
    assert isinstance(stmt, PrintStmt)
    return stmt.expr


def test_and_parses():
    e = _expr("a && b")
    assert isinstance(e, BinaryOp) and e.op == "&&"


def test_not_parses():
    e = _expr("!a")
    assert isinstance(e, UnaryOp) and e.op == "!"


def test_precedence_comparison_binds_tighter_than_and():
    e = _expr("a == b && c == d")
    assert e.op == "&&"
    assert isinstance(e.left, BinaryOp) and e.left.op == "=="
    assert isinstance(e.right, BinaryOp) and e.right.op == "=="


def test_precedence_and_binds_tighter_than_or():
    e = _expr("a || b && c")
    assert e.op == "||"
    assert isinstance(e.right, BinaryOp) and e.right.op == "&&"
