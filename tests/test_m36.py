"""M36: exception handling (fuck_around / find_out / throw)."""

from tawla.lexer import tokenize
from tawla.parser import parse
from tawla.ast_nodes import TryCatch, Throw


def _stmts(body):
    # parse a function body's statements out of a tiny program
    items = parse(tokenize("class Main { void main() { " + body + " } }"))
    main_cls = items[0]
    method = main_cls.methods[0]
    return method.body


def test_parses_trycatch_with_var():
    body = 'fuck_around { throw "x"; } find_out (e) { print(e); }'
    stmts = _stmts(body)
    tc = stmts[0]
    assert isinstance(tc, TryCatch)
    assert tc.catch_var == "e"
    assert isinstance(tc.try_body[0], Throw)


def test_parses_bare_find_out():
    stmts = _stmts('fuck_around { panic("boom"); } find_out { print("caught"); }')
    assert isinstance(stmts[0], TryCatch)
    assert stmts[0].catch_var is None


def test_sema_throw_requires_string(run_twl):
    r = run_twl('fuck_around { throw 5; } find_out (e) { print(e); }')
    assert r.returncode != 0
    assert "string" in r.stderr


def test_throw_caught(run_twl):
    src = 'fuck_around { throw "boom"; print("unreached"); } find_out (e) { print(e); }'
    assert run_twl(src).stdout == "boom\n"


def test_bare_find_out(run_twl):
    src = 'fuck_around { throw "x"; } find_out { print("caught"); }'
    assert run_twl(src).stdout == "caught\n"


def test_panic_caught(run_twl):
    src = 'fuck_around { panic("nope"); } find_out (e) { print(e); } print("after");'
    assert run_twl(src).stdout == "nope\nafter\n"


def test_uncaught_throw_exits_nonzero(run_twl):
    r = run_twl('throw "unhandled";')
    assert r.returncode != 0
    assert "unhandled" in r.stdout


def test_no_throw_runs_try_only(run_twl):
    src = 'fuck_around { print("ok"); } find_out (e) { print("nope"); }'
    assert run_twl(src).stdout == "ok\n"


def test_nested_inner_catches(run_twl):
    src = (
        'fuck_around {'
        '  fuck_around { throw "inner"; } find_out (e) { print(e); }'
        '  print("outer continues");'
        '} find_out (e) { print("outer caught"); }'
    )
    assert run_twl(src).stdout == "inner\nouter continues\n"


def test_rethrow_to_outer(run_twl):
    src = (
        'fuck_around {'
        '  fuck_around { throw "x"; } find_out (e) { throw "y"; }'
        '} find_out (e) { print(e); }'
    )
    assert run_twl(src).stdout == "y\n"


def test_return_from_try(run_twl):
    src = (
        "class Main {"
        "  int f() { fuck_around { return 7; } find_out (e) { return -1; } }"
        "  void main() { print(this.f()); }"
        "}"
    )
    assert run_twl(src).stdout == "7\n"


def test_return_from_catch(run_twl):
    src = (
        "class Main {"
        '  int f() { fuck_around { throw "x"; return 7; } find_out (e) { return -1; } }'
        "  void main() { print(this.f()); }"
        "}"
    )
    assert run_twl(src).stdout == "-1\n"


def test_null_deref_caught(run_twl):
    src = (
        "class Box { public int n; public Box() { this.n = 1; } }"
        "class Main { void main() {"
        '  fuck_around { Box b; print(b.n); } find_out (e) { print("caught null"); }'
        "} }"
    )
    assert run_twl(src).stdout == "caught null\n"


def test_bounds_caught(run_twl):
    src = (
        'fuck_around { int[] a = new int[2]; print(a[5]); }'
        ' find_out (e) { print("caught oob"); }'
    )
    assert run_twl(src).stdout == "caught oob\n"
