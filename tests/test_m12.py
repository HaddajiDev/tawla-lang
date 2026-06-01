"""M12: super constructor chaining."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError

BASE = (
    "class Animal { int legs; Animal(int n) { this.legs = n; } "
    "public int legCount() { return this.legs; } } "
)


def test_super_initializes_base_field(run_twl):
    src = (
        BASE
        + "class Dog : Animal { Dog() { super(4); } } "
        + "print(new Dog().legCount());"
    )
    assert run_twl(src).stdout == "4\n"


def test_super_then_own_field(run_twl):
    src = (
        BASE
        + "class Dog : Animal { int tail; Dog(int t) { super(4); this.tail = t; } "
        + "public int tailLen() { return this.tail; } } "
        + "var d = new Dog(9); print(d.legCount()); print(d.tailLen());"
    )
    assert run_twl(src).stdout == "4\n9\n"


def test_super_through_two_levels(run_twl):
    src = (
        BASE
        + "class Dog : Animal { Dog() { super(4); } } "
        + "class Puppy : Dog { Puppy() { super(); } } "   # Dog() takes no args
        + "print(new Puppy().legCount());"
    )
    assert run_twl(src).stdout == "4\n"


@pytest.mark.parametrize(
    "src",
    [
        # super outside a constructor
        BASE + "class Dog : Animal { Dog() { super(4); } int f() { super(4); return 0; } }",
        # super in a class with no base
        "class A { A() { super(); } }",
        # wrong argument types to base constructor
        BASE + 'class Dog : Animal { Dog() { super("x"); } }',
    ],
)
def test_super_errors(src):
    with pytest.raises(SemaError):
        run_source(src)
