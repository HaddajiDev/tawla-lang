"""M6: classes — fields, methods, this, constructors, new, name mangling."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError

POINT = (
    "class Point { int x; int y; "
    "Point(int px, int py) { this.x = px; this.y = py; } "
    "int sum() { return this.x + this.y; } "
    "int scaled(int k) { return this.x * k + this.y * k; } } "
)


def test_fields_constructor_method(run_twl):
    assert run_twl(POINT + "var p = new Point(3, 4); print(p.sum());").stdout == "7\n"


def test_method_with_param(run_twl):
    assert run_twl(POINT + "var p = new Point(3, 4); print(p.scaled(10));").stdout == "70\n"


def test_field_mutation_and_method_call_statement(run_twl):
    src = (
        "class Acc { int n; Acc() { this.n = 0; } "
        "int add(int x) { this.n = this.n + x; return this.n; } } "
        "var a = new Acc(); a.add(5); a.add(5); print(a.add(0));"
    )
    assert run_twl(src).stdout == "10\n"


def test_instances_are_independent(run_twl):
    src = (
        "class Acc { int n; Acc() { this.n = 0; } "
        "int add(int x) { this.n = this.n + x; return this.n; } } "
        "var a = new Acc(); var b = new Acc(); "
        "a.add(5); b.add(100); print(a.add(0)); print(b.add(0));"
    )
    assert run_twl(src).stdout == "5\n100\n"


def test_name_mangling_avoids_collision(run_twl):
    # Both classes have a method named `value`; mangling keeps them distinct.
    src = (
        "class A { A() {} int value() { return 1; } } "
        "class B { B() {} int value() { return 2; } } "
        "print(new A().value()); print(new B().value());"
    )
    assert run_twl(src).stdout == "1\n2\n"


def test_object_as_function_arg_and_field_read(run_twl):
    src = (
        "class Box { int v; Box(int v) { this.v = v; } } "
        "int unbox(Box b) { return b.v; } "
        "print(unbox(new Box(42)));"
    )
    assert run_twl(src).stdout == "42\n"


def test_bool_field(run_twl):
    src = (
        "class Flag { bool on; Flag(bool v) { this.on = v; } bool get() { return this.on; } } "
        "print(new Flag(true).get());"
    )
    assert run_twl(src).stdout == "1\n"


# --- type / name errors -----------------------------------------------------

@pytest.mark.parametrize(
    "src",
    [
        "var p = new Nope();",                                    # unknown class
        "class C { int x; C() {} } var c = new C(); print(c.y);",  # no such field
        "class C { int x; C(int a) { this.x = a; } } var c = new C(true);",  # bad arg type
        "class C { C() {} } var c = new C(); c.go();",            # no such method
        "int f() { return 1; } int g() { return this.x; }",       # this outside a method
        "class C { int x; C() { this.x = true; } }",              # field type mismatch
        "class C { int x; } var c = new C(5);",                   # default ctor takes no args
    ],
)
def test_class_errors_rejected(src):
    with pytest.raises(SemaError):
        run_source(src)
