"""M24: the bundled IO standard-library module (import "IO.twl")."""

import subprocess
import sys
from pathlib import Path

import pytest

from tawla.ast_nodes import FuncDecl
from tawla.compiler import run_source
from tawla.loader import load_program
from tawla.sema import SemaError

ROOT = Path(__file__).resolve().parent.parent


def run_io(tmp_path, src: str, stdin: str) -> subprocess.CompletedProcess:
    prog = tmp_path / "prog.twl"
    prog.write_text(src, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "tawla", "run", str(prog)],
        input=stdin, capture_output=True, text=True, cwd=ROOT,
    )


def test_io_module_resolves_from_stdlib(tmp_path):
    """import "IO.twl" finds the bundled file even with nothing local."""
    entry = tmp_path / "prog.twl"
    entry.write_text('import "IO.twl"; class Main { void main() {} }', encoding="utf-8")
    names = {it.name for it in load_program(entry) if isinstance(it, FuncDecl)}
    assert {"readLine", "readInt", "readFloat", "write"} <= names


def test_read_int(tmp_path):
    src = (
        'import "IO.twl";'
        " class Main { void main() { int n = readInt(); print(n + 1); } }"
    )
    result = run_io(tmp_path, src, "41\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "42\n"


def test_read_line(tmp_path):
    src = (
        'import "IO.twl";'
        " class Main { void main() { string s = readLine(); print(s); } }"
    )
    result = run_io(tmp_path, src, "hello world\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "hello world\n"


def test_read_float(tmp_path):
    src = (
        'import "IO.twl";'
        " class Main { void main() { float x = readFloat(); print(x * 2.0); } }"
    )
    result = run_io(tmp_path, src, "1.5\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "3\n"


def test_write_has_no_newline(tmp_path):
    src = (
        'import "IO.twl";'
        ' class Main { void main() { write("a"); write("b"); print("c"); } }'
    )
    result = run_io(tmp_path, src, "")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "abc\n"


def test_prompt_then_read(tmp_path):
    src = (
        'import "IO.twl";'
        ' class Main { void main() {'
        ' write("n? "); int n = readInt(); write("got "); print(n); } }'
    )
    result = run_io(tmp_path, src, "7\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "n? got 7\n"


def test_read_non_number_is_zero(tmp_path):
    src = (
        'import "IO.twl";'
        " class Main { void main() { int n = readInt(); print(n); } }"
    )
    result = run_io(tmp_path, src, "notanumber\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "0\n"


def test_io_functions_need_the_import():
    """Without importing IO.twl, the names aren't defined."""
    with pytest.raises(SemaError):
        run_source('class Main { void main() { write("hi"); } }')
