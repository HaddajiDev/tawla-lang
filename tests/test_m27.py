"""M27: collections (List / Map) and the panic builtin."""

import pytest

from tawla.compiler import run_source
from tawla.sema import SemaError


def _err(result):
    return result.stdout + result.stderr


def test_panic_aborts(run_twl):
    src = 'class Main { void main() { print(1); panic("boom"); print(2); } }'
    r = run_twl(src)
    assert r.returncode != 0
    assert "boom" in _err(r)
    assert "1\n" in r.stdout       # ran before the panic
    assert "2" not in r.stdout     # never reached


def test_panic_wrong_arg_type_is_error():
    with pytest.raises(SemaError):
        run_source("panic(5);")


from tawla.ast_nodes import BinaryOp, ExprStmt, VarDecl
from tawla.lexer import tokenize
from tawla.parser import parse


def test_generic_typed_local_declaration_parses():
    items = parse(tokenize("Box<int> b = makeBox();"))
    assert isinstance(items[0], VarDecl)
    assert items[0].var_type == "Box<int>"
    assert items[0].name == "b"


def test_comparison_statement_still_parses():
    items = parse(tokenize("a < b;"))
    assert isinstance(items[0], ExprStmt)
    assert isinstance(items[0].expr, BinaryOp)


LIST_HEADER = 'import "Collections.twl"; class Main { void main() { '
FOOTER = ' } }'


def test_list_basic(run_twl):
    src = LIST_HEADER + (
        "List<int> xs = new List<int>();"
        " xs.add(10); xs.add(20); xs.add(30);"
        " print(xs.size()); print(xs.get(0)); print(xs.get(2));"
    ) + FOOTER
    assert run_twl(src).stdout == "3\n10\n30\n"


def test_list_set(run_twl):
    src = LIST_HEADER + (
        "List<int> xs = new List<int>(); xs.add(1); xs.set(0, 99); print(xs.get(0));"
    ) + FOOTER
    assert run_twl(src).stdout == "99\n"


def test_list_grows_past_initial_capacity(run_twl):
    src = LIST_HEADER + (
        "List<int> xs = new List<int>();"
        " for (int j = 0; j < 10; j = j + 1) { xs.add(j * j); }"
        " print(xs.size()); print(xs.get(9));"
    ) + FOOTER
    assert run_twl(src).stdout == "10\n81\n"


def test_list_out_of_range_panics(run_twl):
    src = LIST_HEADER + "List<int> xs = new List<int>(); xs.add(1); print(xs.get(5));" + FOOTER
    r = run_twl(src)
    assert r.returncode != 0
    assert "out of range" in _err(r)


def test_map_basic(run_twl):
    src = LIST_HEADER + (
        'Map<string, int> m = new Map<string, int>();'
        ' m.put("ada", 36); m.put("bob", 7);'
        ' print(m.size()); print(m.get("ada")); print(m.get("bob"));'
    ) + FOOTER
    assert run_twl(src).stdout == "2\n36\n7\n"


def test_map_overwrite(run_twl):
    src = LIST_HEADER + (
        'Map<string, int> m = new Map<string, int>();'
        ' m.put("x", 1); m.put("x", 2); print(m.size()); print(m.get("x"));'
    ) + FOOTER
    assert run_twl(src).stdout == "1\n2\n"


def test_map_has(run_twl):
    src = LIST_HEADER + (
        'Map<string, int> m = new Map<string, int>(); m.put("x", 1);'
        ' if (m.has("x")) { print(1); } if (m.has("y")) { print(2); } else { print(3); }'
    ) + FOOTER
    assert run_twl(src).stdout == "1\n3\n"


def test_map_missing_value_type_is_zero(run_twl):
    src = LIST_HEADER + (
        'Map<string, int> m = new Map<string, int>(); print(m.get("nope"));'
    ) + FOOTER
    assert run_twl(src).stdout == "0\n"


def test_map_missing_reference_type_is_null(run_twl):
    src = (
        'import "Collections.twl";'
        ' class User { public int id; }'
        ' class Main { void main() {'
        ' Map<string, User> m = new Map<string, User>();'
        ' User u = m.get("nope"); if (u == null) { print(1); } } }'
    )
    assert run_twl(src).stdout == "1\n"
