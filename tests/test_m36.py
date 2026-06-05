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
