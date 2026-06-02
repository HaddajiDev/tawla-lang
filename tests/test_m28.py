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


from tawla.sema import SemaError, check


def _sema(src):
    return check(parse(tokenize(src)))


def test_and_or_not_typecheck_ok():
    _sema("class Main { void main() { bool b = true && false || !true; } }")


def test_and_requires_bool():
    with pytest.raises(SemaError):
        _sema("class Main { void main() { bool b = 1 && 2; } }")


def test_not_requires_bool():
    with pytest.raises(SemaError):
        _sema("class Main { void main() { bool b = !5; } }")


TRUTH = [
    ("true && true", "1"), ("true && false", "0"),
    ("false && true", "0"), ("false && false", "0"),
    ("true || false", "1"), ("false || false", "0"),
    ("false || true", "1"), ("!true", "0"), ("!false", "1"),
]


@pytest.mark.parametrize("expr,out", TRUTH)
def test_truth_tables(run_twl, expr, out):
    src = "class Main { void main() { if (" + expr + ") { print(1); } else { print(0); } } }"
    assert run_twl(src).stdout == out + "\n"


def test_precedence_runs(run_twl):
    src = "class Main { void main() { if (1 == 1 && 2 == 2) { print(1); } else { print(0); } } }"
    assert run_twl(src).stdout == "1\n"


def test_and_short_circuits(run_twl):
    src = (
        "class A { public int v() { return 1; } }"
        " class Main { void main() {"
        " A a = null; if (a != null && a.v() == 1) { print(2); } else { print(1); } } }"
    )
    r = run_twl(src)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout == "1\n"


def test_or_short_circuits(run_twl):
    src = (
        "class A { public int v() { return 1; } }"
        " class Main { void main() {"
        " A a = null; if (a == null || a.v() == 1) { print(1); } } }"
    )
    r = run_twl(src)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout == "1\n"
