"""M26: encapsulation (public / protected / private)."""

import pytest

from tawla.ast_nodes import CtorDecl, FieldDecl, MethodDecl
from tawla.lexer import tokenize
from tawla.parser import parse


def _members(src):
    return parse(tokenize(src))[0]


def test_field_defaults_private():
    cls = _members("class A { int x; }")
    assert cls.fields[0].visibility == "private"


def test_method_defaults_private():
    cls = _members("class A { int m() { return 0; } }")
    assert cls.methods[0].visibility == "private"


def test_constructor_defaults_public():
    cls = _members("class A { int x; A(int v) { this.x = v; } }")
    assert cls.ctor.visibility == "public"


def test_explicit_modifiers_parse():
    cls = _members(
        "class A { public int x; protected int y; private int z;"
        " public int m() { return 0; } private A() {} }"
    )
    vis = {f.name: f.visibility for f in cls.fields}
    assert vis == {"x": "public", "y": "protected", "z": "private"}
    assert cls.methods[0].visibility == "public"
    assert cls.ctor.visibility == "private"


def test_public_abstract_method_parses():
    cls = _members("abstract class A { public abstract int m(); }")
    assert cls.methods[0].is_abstract
    assert cls.methods[0].visibility == "public"


from tawla.sema import SemaError, check


def _sema(src):
    return check(parse(tokenize(src)))


def test_public_method_callable_from_outside():
    _sema(
        "class A { public int m() { return 1; } }"
        " class Main { void main() { A a = new A(); print(a.m()); } }"
    )


def test_private_method_not_callable_from_outside():
    with pytest.raises(SemaError):
        _sema(
            "class A { private int m() { return 1; } }"
            " class Main { void main() { A a = new A(); print(a.m()); } }"
        )


def test_private_member_usable_within_same_class():
    _sema("class A { private int x; public int get() { return this.x; } }")


def test_protected_field_usable_in_subclass():
    _sema(
        "class A { protected int x; }"
        " class B : A { public int get() { return this.x; } }"
    )


def test_protected_field_not_usable_from_outside():
    with pytest.raises(SemaError):
        _sema(
            "class A { protected int x; }"
            " class Main { void main() { A a = new A(); print(a.x); } }"
        )


def test_private_field_not_usable_in_subclass():
    with pytest.raises(SemaError):
        _sema(
            "class A { private int x; }"
            " class B : A { public int get() { return this.x; } }"
        )


def test_private_field_not_usable_from_outside():
    with pytest.raises(SemaError):
        _sema(
            "class A { private int x; }"
            " class Main { void main() { A a = new A(); print(a.x); } }"
        )


def test_private_constructor_blocks_new_from_outside():
    with pytest.raises(SemaError):
        _sema(
            "class A { private A() {} }"
            " class Main { void main() { A a = new A(); } }"
        )


def test_public_constructor_allows_new():
    _sema(
        "class A { public A() {} }"
        " class Main { void main() { A a = new A(); } }"
    )


def test_interface_impl_must_be_public():
    with pytest.raises(SemaError):
        _sema(
            "interface Shape { int area(); }"
            " class Sq : Shape { private int area() { return 1; } }"
        )


def test_abstract_method_cannot_be_private():
    with pytest.raises(SemaError):
        _sema("abstract class A { private abstract int m(); }")


def test_override_must_keep_visibility():
    with pytest.raises(SemaError):
        _sema(
            "class A { public int m() { return 1; } }"
            " class B : A { private int m() { return 2; } }"
        )
