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


def test_typed_decl_without_initializer_parses():
    from tawla.ast_nodes import VarDecl
    items = parse(tokenize("int x;"))
    assert isinstance(items[0], VarDecl)
    assert items[0].init is None


def test_decl_with_initializer_still_parses():
    from tawla.ast_nodes import VarDecl
    items = parse(tokenize("int x = 5;"))
    assert isinstance(items[0], VarDecl)
    assert items[0].init is not None


def test_monomorphize_keeps_none_init():
    from tawla.monomorphize import monomorphize
    src = (
        "class Box<T> { T v; }"
        " class Main { void main() { int x; var b = new Box<int>(); } }"
    )
    monomorphize(parse(tokenize(src)))  # must not raise (init is None for `int x;`)


from tawla.sema import SemaError, check


def _sema(src):
    return check(parse(tokenize(src)))


def test_null_assignable_to_class():
    _sema("class A {} class Main { void main() { A a = null; } }")


def test_null_assignable_to_string_and_array():
    _sema("class Main { void main() { string s = null; int[] a = null; } }")


def test_null_not_assignable_to_int():
    with pytest.raises(SemaError):
        _sema("class Main { void main() { int x = null; } }")


def test_var_assigned_null_is_error():
    with pytest.raises(SemaError):
        _sema("class Main { void main() { var z = null; } }")


def test_uninitialized_typed_decls_ok():
    _sema("class A {} class Main { void main() { int x; bool b; string s; A a; } }")


def test_uninitialized_var_is_error():
    with pytest.raises(SemaError):
        _sema("class Main { void main() { var z; } }")


def test_compare_reference_to_null_ok():
    _sema("class A {} class Main { void main() { A a = null; if (a == null) {} } }")


def test_compare_int_to_null_is_error():
    with pytest.raises(SemaError):
        _sema("class Main { void main() { int x = 0; if (x == null) {} } }")
