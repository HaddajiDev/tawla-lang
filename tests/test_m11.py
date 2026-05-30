"""M11: void methods/functions and the `Main` entry-point convention."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError


def test_void_function(run_twl):
    src = 'void hi() { print("hi"); } hi();'
    assert run_twl(src).stdout == "hi\n"


def test_void_method_called_as_statement(run_twl):
    src = (
        'class Logger { void log() { print("logged"); } } '
        "var l = new Logger(); l.log();"
    )
    assert run_twl(src).stdout == "logged\n"


def test_void_method_with_bare_return(run_twl):
    src = (
        "class C { void f(int n) { if (n < 0) { return; } print(n); } } "
        "var c = new C(); c.f(5); c.f(-1);"
    )
    assert run_twl(src).stdout == "5\n"


def test_main_entry_convention(run_twl):
    # No top-level statements: `new Main().main()` runs automatically.
    src = 'class Main { void main() { print("Hello, Tawla!"); } }'
    assert run_twl(src).stdout == "Hello, Tawla!\n"


def test_default_constructor(run_twl):
    # A class with no constructor can be `new`'d with no args.
    src = 'class Main { void main() { print(7); } }'
    assert run_twl(src).stdout == "7\n"


@pytest.mark.parametrize(
    "src",
    [
        "void f() { return 1; }",                 # value from void
        "int f() { return; }",                    # bare return from non-void
        "void x = 0;",                            # void variable
        'void v() {} var x = v();',               # void used as a value
        "class C { void f() {} } void g(C c) { int x = c.f(); }",  # void in expr
    ],
)
def test_void_errors(src):
    with pytest.raises(SemaError):
        run_source(src)
