"""M7: inheritance — inherited fields/methods, override, subtyping (static dispatch)."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError

BASE = (
    "class Animal { int legs; Animal(int n) { this.legs = n; } "
    "int legCount() { return this.legs; } int speak() { return 0; } } "
    "class Dog : Animal { Dog() { this.legs = 4; } int speak() { return 1; } } "
)


def test_inherited_field_and_method(run_twl):
    assert run_twl(BASE + "print(new Dog().legCount());").stdout == "4\n"


def test_override(run_twl):
    assert run_twl(BASE + "print(new Dog().speak());").stdout == "1\n"


def test_inherited_method_uses_inherited_field(run_twl):
    # legCount is defined on Animal and reads `this.legs`, set by Dog's ctor.
    assert run_twl(BASE + "var d = new Dog(); print(d.legCount());").stdout == "4\n"


def test_subtype_variable_dispatch(run_twl):
    # a's static type is Animal but it holds a Dog. As of M8 (vtables) this
    # dispatches dynamically and returns Dog's 1. (In M7 alone it was 0.)
    src = BASE + "Animal a = new Dog(); print(a.speak());"
    assert run_twl(src).stdout == "1\n"


def test_subtype_field_through_base_type(run_twl):
    src = BASE + "Animal a = new Dog(); print(a.legs);"
    assert run_twl(src).stdout == "4\n"


def test_subtype_as_function_argument(run_twl):
    src = BASE + "int count(Animal a) { return a.legCount(); } print(count(new Dog()));"
    assert run_twl(src).stdout == "4\n"


def test_three_level_inheritance(run_twl):
    src = (
        "class A { int v; A() { this.v = 1; } int get() { return this.v; } } "
        "class B : A { B() { this.v = 2; } } "
        "class C : B { C() { this.v = 3; } } "
        "print(new C().get());"   # get inherited from A, reads v set by C's ctor
    )
    assert run_twl(src).stdout == "3\n"


# --- errors -----------------------------------------------------------------

@pytest.mark.parametrize(
    "src",
    [
        "class B : Nope { B() {} }",                                    # unknown base
        "class A { A() {} int f() { return 0; } } "
        "class B : A { B() {} bool f() { return true; } }",            # bad override sig
        "class A { A() {} } class B : A { B() {} } "
        "A x = new A(); B y = x;",                                      # base -> subclass
    ],
)
def test_inheritance_errors(src):
    with pytest.raises(SemaError):
        run_source(src)
