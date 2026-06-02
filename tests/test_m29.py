"""M29: ternary operator (cond ? a : b)."""

import pytest

from tawla.ast_nodes import BinaryOp, PrintStmt, Ternary
from tawla.lexer import tokenize
from tawla.monomorphize import monomorphize
from tawla.parser import parse
from tawla.tokens import TokenKind


def _expr(src):
    stmt = parse(tokenize("print(" + src + ");"))[0]
    assert isinstance(stmt, PrintStmt)
    return stmt.expr


def test_question_lexes():
    assert tokenize("?")[0].kind is TokenKind.QUESTION


def test_ternary_parses():
    e = _expr("a ? b : c")
    assert isinstance(e, Ternary)


def test_ternary_is_right_associative():
    e = _expr("a ? b : c ? d : e")
    assert isinstance(e, Ternary)
    assert isinstance(e.else_expr, Ternary)


def test_ternary_lower_precedence_than_or():
    e = _expr("p || q ? x : y")
    assert isinstance(e, Ternary)
    assert isinstance(e.cond, BinaryOp) and e.cond.op == "||"


def test_monomorphize_traverses_ternary():
    src = (
        "class Box<T> { public T v; }"
        " class Main { void main() { bool t = true; int x = t ? 1 : 2;"
        " var b = new Box<int>(); } }"
    )
    monomorphize(parse(tokenize(src)))  # must not raise
