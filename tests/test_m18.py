"""M18: generics via monomorphization."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError

BOX = (
    "class Box<T> { T value; Box(T v) { this.value = v; } "
    "public T get() { return this.value; } public void set(T v) { this.value = v; } } "
)


def test_generic_box_int(run_twl):
    assert run_twl(BOX + "var b = new Box<int>(42); print(b.get());").stdout == "42\n"


def test_generic_box_string(run_twl):
    assert run_twl(BOX + 'var b = new Box<string>("hi"); print(b.get());').stdout == "hi\n"


def test_two_instantiations_coexist(run_twl):
    src = BOX + (
        'var a = new Box<int>(5); var b = new Box<string>("x"); '
        "print(a.get()); print(b.get());"
    )
    assert run_twl(src).stdout == "5\nx\n"


def test_generic_with_two_params(run_twl):
    src = (
        "class Pair<A, B> { A a; B b; Pair(A a, B b) { this.a = a; this.b = b; } "
        "public A first() { return this.a; } public B second() { return this.b; } } "
        'var p = new Pair<int, string>(7, "seven"); print(p.first()); print(p.second());'
    )
    assert run_twl(src).stdout == "7\nseven\n"


def test_generic_of_class_type(run_twl):
    src = (
        "class Cell { int v; Cell(int v) { this.v = v; } public int get() { return this.v; } } "
        + BOX
        + "var b = new Box<Cell>(new Cell(99)); print(b.get().get());"
    )
    assert run_twl(src).stdout == "99\n"


def test_generic_mutation(run_twl):
    src = BOX + "var b = new Box<int>(1); b.set(100); print(b.get());"
    assert run_twl(src).stdout == "100\n"


@pytest.mark.parametrize(
    "src",
    [
        BOX + "var b = new Box<int>(true);",          # wrong type arg to ctor
        BOX + "var b = new Box<int, int>(1);",        # wrong arity
        "var b = new NotGeneric<int>(1);",            # not a generic class
    ],
)
def test_generic_errors(src):
    with pytest.raises(SemaError):
        run_source(src)
