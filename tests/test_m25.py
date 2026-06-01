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


def test_null_equality_true(run_twl):
    src = (
        "class A {} class Main { void main() {"
        " A a = null; if (a == null) { print(1); } else { print(2); } } }"
    )
    assert run_twl(src).stdout == "1\n"


def test_reassign_makes_not_null(run_twl):
    src = (
        "class A { int x; } class Main { void main() {"
        " A a = null; a = new A(); if (a != null) { print(1); } } }"
    )
    assert run_twl(src).stdout == "1\n"


def test_default_int_is_zero(run_twl):
    assert run_twl("class Main { void main() { int x; print(x); } }").stdout == "0\n"


def test_default_bool_is_false(run_twl):
    src = "class Main { void main() { bool b; if (b) { print(1); } else { print(0); } } }"
    assert run_twl(src).stdout == "0\n"


def test_default_float_is_zero(run_twl):
    assert run_twl("class Main { void main() { float f; print(f); } }").stdout == "0\n"


def test_object_field_defaults_to_null(run_twl):
    src = (
        "class Node { Node next; }"
        " class Main { void main() { Node n = new Node(); if (n.next == null) { print(1); } } }"
    )
    assert run_twl(src).stdout == "1\n"


def test_null_string_compares_equal(run_twl):
    src = "class Main { void main() { string s; if (s == null) { print(1); } } }"
    assert run_twl(src).stdout == "1\n"
