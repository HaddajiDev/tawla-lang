"""Shared test helpers.

`run_twl` compiles and runs a Tawla program by invoking the CLI as a
subprocess, so the child's stdout is captured cleanly via a pipe. This avoids
the Windows C-runtime fd-table mismatch that defeats in-process capture of
JIT'd `printf` output.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def run_twl(tmp_path):
    def _run(src: str) -> subprocess.CompletedProcess:
        prog = tmp_path / "prog.twl"
        prog.write_text(src, encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-m", "tawla", "run", str(prog)],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )

    return _run
