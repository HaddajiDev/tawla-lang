"""M9b: abstract classes and abstract methods."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError

ABSTRACT = (
    "abstract class Animal { int legs; abstract int speak(); "
    "int legCount() { return this.legs; } } "
    "class Dog : Animal { Dog() { this.legs = 4; } int speak() { return 1; } } "
    "class Cat : Animal { Cat() { this.legs = 4; } int speak() { return 2; } } "
)


def test_abstract_method_dispatch(run_twl):
    src = ABSTRACT + "int sp(Animal a) { return a.speak(); } " \
        "print(sp(new Dog())); print(sp(new Cat()));"
    assert run_twl(src).stdout == "1\n2\n"


def test_concrete_method_inherited_from_abstract(run_twl):
    assert run_twl(ABSTRACT + "print(new Dog().legCount());").stdout == "4\n"


def test_abstract_base_typed_variable_dispatches(run_twl):
    assert run_twl(ABSTRACT + "Animal a = new Cat(); print(a.speak());").stdout == "2\n"


@pytest.mark.parametrize(
    "src",
    [
        # cannot instantiate an abstract class
        "abstract class A { abstract int f(); } var x = new A();",
        # concrete subclass must implement the abstract method
        "abstract class A { abstract int f(); } class B : A { B() {} }",
        # abstract method in a non-abstract class
        "class A { abstract int f(); }",
    ],
)
def test_abstract_errors(src):
    with pytest.raises(SemaError):
        run_source(src)
