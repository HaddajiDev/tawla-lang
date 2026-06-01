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
