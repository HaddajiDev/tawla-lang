"""M9a: interfaces — fat-pointer values and itable-based dynamic dispatch."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError

SHAPES = (
    "interface Shape { int area(); } "
    "class Square : Shape { int side; Square(int s) { this.side = s; } "
    "public int area() { return this.side * this.side; } } "
    "class Box : Shape { int w; int h; Box(int w, int h) { this.w = w; this.h = h; } "
    "public int area() { return this.w * this.h; } } "
)


def test_interface_dispatch_unrelated_classes(run_twl):
    # Square and Box share no base class, yet both satisfy Shape.
    src = SHAPES + "int areaOf(Shape s) { return s.area(); } " \
        "print(areaOf(new Square(5))); print(areaOf(new Box(3, 4)));"
    assert run_twl(src).stdout == "25\n12\n"


def test_interface_typed_variable(run_twl):
    assert run_twl(SHAPES + "Shape s = new Square(10); print(s.area());").stdout == "100\n"


def test_interface_with_multiple_methods(run_twl):
    src = (
        "interface Shape { int area(); int sides(); } "
        "class Sq : Shape { int s; Sq(int s) { this.s = s; } "
        "public int area() { return this.s * this.s; } public int sides() { return 4; } } "
        "int describe(Shape x) { return x.area() + x.sides(); } "
        "print(describe(new Sq(5)));"
    )
    assert run_twl(src).stdout == "29\n"


def test_class_implements_multiple_interfaces(run_twl):
    src = (
        "interface Named { int id(); } interface Sized { int size(); } "
        "class Thing : Named, Sized { Thing() {} public int id() { return 7; } public int size() { return 42; } } "
        "Named n = new Thing(); Sized z = new Thing(); print(n.id()); print(z.size());"
    )
    assert run_twl(src).stdout == "7\n42\n"


def test_interface_implemented_via_base_class(run_twl):
    src = (
        "interface Greeter { int greet(); } "
        "class Base : Greeter { Base() {} public int greet() { return 1; } } "
        "class Derived : Base { Derived() {} } "
        "Greeter g = new Derived(); print(g.greet());"
    )
    assert run_twl(src).stdout == "1\n"


def test_interface_in_field_and_list_of_shapes(run_twl):
    # Store an interface value in a field and dispatch through it.
    src = (
        SHAPES
        + "class Holder { Shape shape; Holder(Shape s) { this.shape = s; } "
        + "public int area() { return this.shape.area(); } } "
        + "print(new Holder(new Box(2, 9)).area());"
    )
    assert run_twl(src).stdout == "18\n"


# --- errors -----------------------------------------------------------------

@pytest.mark.parametrize(
    "src",
    [
        "interface S { int area(); } class C : S { C() {} }",            # missing method
        "interface S { int area(); } class C : S { C() {} bool area() { return true; } }",  # bad sig
        "interface S { int area(); } var x = new S();",                  # new interface
    ],
)
def test_interface_errors(src):
    with pytest.raises(SemaError):
        run_source(src)
