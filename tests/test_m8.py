"""M8: polymorphism — vtables and dynamic dispatch on the runtime type."""

from tawla.compiler import run_source

BASE = (
    "class Animal { protected int legs; Animal(int n) { this.legs = n; } "
    "public int speak() { return 0; } public int legCount() { return this.legs; } } "
    "class Dog : Animal { Dog() { this.legs = 4; } public int speak() { return 1; } } "
    "class Snake : Animal { Snake() { this.legs = 0; } public int speak() { return 2; } } "
)


def test_dynamic_dispatch_through_base_variable(run_twl):
    # The key M8 behavior: static type Animal, runtime Dog -> Dog.speak().
    assert run_twl(BASE + "Animal a = new Dog(); print(a.speak());").stdout == "1\n"


def test_dynamic_dispatch_through_function_param(run_twl):
    src = BASE + "int sp(Animal a) { return a.speak(); } print(sp(new Snake()));"
    assert run_twl(src).stdout == "2\n"


def test_base_instance_uses_base_method(run_twl):
    assert run_twl(BASE + "Animal a = new Animal(2); print(a.speak());").stdout == "0\n"


def test_inherited_method_still_dispatches(run_twl):
    # legCount is not overridden; the vtable slot points at Animal.legCount.
    assert run_twl(BASE + "Animal a = new Dog(); print(a.legCount());").stdout == "4\n"


def test_polymorphism_over_several_objects(run_twl):
    src = (
        BASE
        + "int sp(Animal a) { return a.speak(); } "
        + "print(sp(new Animal(9))); print(sp(new Dog())); print(sp(new Snake()));"
    )
    assert run_twl(src).stdout == "0\n1\n2\n"


def test_three_level_override_dispatch(run_twl):
    # C overrides; B does not. An A-typed reference to a C must call C's.
    src = (
        "class A { A() {} public int v() { return 1; } } "
        "class B : A { B() {} } "
        "class C : B { C() {} public int v() { return 3; } } "
        "A x = new C(); print(x.v());"
    )
    assert run_twl(src).stdout == "3\n"


def test_run_source_can_compile_twice_in_one_process():
    # Guards the per-module Context fix (identified structs must not collide).
    assert run_source("class P { int x; P() { this.x = 1; } }") == 0
    assert run_source("class P { int x; P() { this.x = 2; } }") == 0
