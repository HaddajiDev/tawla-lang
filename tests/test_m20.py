"""M20: importing other .twl files."""

import subprocess
import sys
from pathlib import Path

import pytest

from tawla.ast_nodes import ClassDecl, FuncDecl, InterfaceDecl
from tawla.loader import LoadError, load_program

ROOT = Path(__file__).resolve().parent.parent


def _names(items):
    return [getattr(it, "name", None) for it in items]


def test_basic_import_merges_declarations(tmp_path):
    (tmp_path / "lib.twl").write_text("class Point { int x; }", encoding="utf-8")
    entry = tmp_path / "main.twl"
    entry.write_text('import "lib.twl"; class Main { void main() {} }', encoding="utf-8")

    items = load_program(entry)
    assert "Point" in _names(items)
    assert "Main" in _names(items)


def test_twl_suffix_is_optional(tmp_path):
    (tmp_path / "lib.twl").write_text("class Point { int x; }", encoding="utf-8")
    entry = tmp_path / "main.twl"
    entry.write_text('import "lib"; class Main { void main() {} }', encoding="utf-8")

    assert "Point" in _names(load_program(entry))


def test_nested_imports(tmp_path):
    (tmp_path / "a.twl").write_text('import "b.twl"; class A {}', encoding="utf-8")
    (tmp_path / "b.twl").write_text("class B {}", encoding="utf-8")
    entry = tmp_path / "main.twl"
    entry.write_text('import "a.twl"; class Main { void main() {} }', encoding="utf-8")

    names = _names(load_program(entry))
    assert {"A", "B", "Main"} <= set(names)


def test_diamond_loads_each_file_once(tmp_path):
    (tmp_path / "base.twl").write_text("class Base {}", encoding="utf-8")
    (tmp_path / "left.twl").write_text('import "base.twl"; class Left {}', encoding="utf-8")
    (tmp_path / "right.twl").write_text('import "base.twl"; class Right {}', encoding="utf-8")
    entry = tmp_path / "main.twl"
    entry.write_text(
        'import "left.twl"; import "right.twl"; class Main { void main() {} }',
        encoding="utf-8",
    )

    names = _names(load_program(entry))
    assert names.count("Base") == 1


def test_import_cycle_terminates(tmp_path):
    (tmp_path / "a.twl").write_text('import "b.twl"; class A {}', encoding="utf-8")
    (tmp_path / "b.twl").write_text('import "a.twl"; class B {}', encoding="utf-8")
    entry = tmp_path / "main.twl"
    entry.write_text('import "a.twl"; class Main { void main() {} }', encoding="utf-8")

    names = _names(load_program(entry))
    assert {"A", "B", "Main"} <= set(names)


def test_relative_to_importing_file(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "lib.twl").write_text("class Deep {}", encoding="utf-8")
    (tmp_path / "sub" / "use.twl").write_text('import "lib.twl"; class Use {}', encoding="utf-8")
    entry = tmp_path / "main.twl"
    entry.write_text('import "sub/use.twl"; class Main { void main() {} }', encoding="utf-8")

    assert "Deep" in _names(load_program(entry))


def test_missing_import_is_an_error(tmp_path):
    entry = tmp_path / "main.twl"
    entry.write_text('import "nope.twl"; class Main { void main() {} }', encoding="utf-8")
    with pytest.raises(LoadError):
        load_program(entry)


def test_statements_in_imported_file_rejected(tmp_path):
    (tmp_path / "lib.twl").write_text('print("hi");', encoding="utf-8")
    entry = tmp_path / "main.twl"
    entry.write_text('import "lib.twl"; class Main { void main() {} }', encoding="utf-8")
    with pytest.raises(LoadError):
        load_program(entry)


def test_entry_file_keeps_its_statements(tmp_path):
    (tmp_path / "lib.twl").write_text("int two() { return 2; }", encoding="utf-8")
    entry = tmp_path / "main.twl"
    entry.write_text('import "lib.twl"; print(two());', encoding="utf-8")

    items = load_program(entry)
    assert any(isinstance(it, FuncDecl) and it.name == "two" for it in items)
    assert items[-1].__class__.__name__ == "PrintStmt"


def test_import_runs_end_to_end(tmp_path):
    (tmp_path / "geometry.twl").write_text(
        "class Point { int x; int y;"
        " Point(int a, int b) { this.x = a; this.y = b; }"
        " int sum() { return this.x + this.y; } }"
        " int area(int w, int h) { return w * h; }",
        encoding="utf-8",
    )
    entry = tmp_path / "main.twl"
    entry.write_text(
        'import "geometry";'
        " class Main { void main() {"
        " var p = new Point(3, 4); print(p.sum()); print(area(5, 6)); } }",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "tawla", "run", str(entry)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "7\n30\n"


def test_imported_interface_and_class(tmp_path):
    (tmp_path / "shapes.twl").write_text(
        "interface Shape { int area(); }"
        " class Square : Shape { int s;"
        " Square(int x) { this.s = x; } int area() { return this.s * this.s; } }",
        encoding="utf-8",
    )
    entry = tmp_path / "main.twl"
    entry.write_text(
        'import "shapes.twl";'
        " class Main { void main() { Shape sh = new Square(4); print(sh.area()); } }",
        encoding="utf-8",
    )

    items = load_program(entry)
    assert any(isinstance(it, InterfaceDecl) and it.name == "Shape" for it in items)
    assert any(isinstance(it, ClassDecl) and it.name == "Square" for it in items)

    result = subprocess.run(
        [sys.executable, "-m", "tawla", "run", str(entry)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "16\n"
