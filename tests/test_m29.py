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


from tawla.sema import SemaError, check


def _sema(src):
    return check(parse(tokenize(src)))


def test_ternary_typechecks_ok():
    _sema("class Main { void main() { int x = true ? 1 : 2; } }")


def test_ternary_int_float_common_type_is_float():
    _sema("class Main { void main() { float x = true ? 1 : 2.0; } }")
    with pytest.raises(SemaError):
        _sema("class Main { void main() { int x = true ? 1 : 2.0; } }")


def test_ternary_condition_must_be_bool():
    with pytest.raises(SemaError):
        _sema("class Main { void main() { int x = 5 ? 1 : 2; } }")


def test_ternary_incompatible_branches_error():
    with pytest.raises(SemaError):
        _sema('class Main { void main() { var x = true ? 1 : "s"; } }')


def test_ternary_selects_then(run_twl):
    assert run_twl("class Main { void main() { print(true ? 1 : 2); } }").stdout == "1\n"


def test_ternary_selects_else(run_twl):
    assert run_twl("class Main { void main() { print(false ? 1 : 2); } }").stdout == "2\n"


def test_ternary_int_float_runs_as_float(run_twl):
    src = "class Main { void main() { print((true ? 7 : 0) / 2.0); } }"
    assert run_twl(src).stdout == "3.5\n"


def test_ternary_nesting(run_twl):
    src = (
        "int label(int n) { return n == 0 ? 10 : n == 1 ? 20 : 30; }"
        " class Main { void main() { print(label(0)); print(label(1)); print(label(2)); } }"
    )
    assert run_twl(src).stdout == "10\n20\n30\n"


def test_ternary_is_lazy(run_twl):
    src = (
        "class A { public int v() { return 1; } }"
        " class Main { void main() {"
        " A a = null; int id = a != null ? a.v() : 0; print(id); } }"
    )
    r = run_twl(src)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout == "0\n"


def test_ternary_with_objects(run_twl):
    src = (
        "class A { public int who() { return 1; } }"
        " class Main { void main() {"
        " A x = new A(); A y = new A(); A z = true ? x : y; print(z.who()); } }"
    )
    assert run_twl(src).stdout == "1\n"
