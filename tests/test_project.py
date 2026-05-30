"""Cargo-style project support: Tawla.toml, scaffolding, and project-mode run."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tawla.project import ProjectError, entry_path, find_manifest, scaffold

ROOT = Path(__file__).resolve().parent.parent


def _tawlac(args, cwd):
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "tawla", *args],
        cwd=cwd, capture_output=True, text=True, env=env,
    )


def test_scaffold_creates_layout(tmp_path):
    proj = tmp_path / "demo"
    scaffold(proj, "demo")
    assert (proj / "Tawla.toml").is_file()
    assert (proj / "src" / "main.twl").is_file()
    assert 'name = "demo"' in (proj / "Tawla.toml").read_text()


def test_scaffold_refuses_to_overwrite(tmp_path):
    scaffold(tmp_path, "demo")
    with pytest.raises(ProjectError):
        scaffold(tmp_path, "demo")


def test_find_manifest_walks_upward(tmp_path):
    scaffold(tmp_path, "demo")
    deep = tmp_path / "src"
    assert find_manifest(deep) == tmp_path / "Tawla.toml"


def test_entry_path_from_manifest(tmp_path):
    scaffold(tmp_path, "demo")
    assert entry_path(tmp_path / "Tawla.toml") == tmp_path / "src" / "main.twl"


def test_new_then_run_project(tmp_path):
    created = _tawlac(["new", "demo"], cwd=tmp_path)
    assert created.returncode == 0
    proj = tmp_path / "demo"
    assert (proj / "Tawla.toml").is_file()

    # `tawlac run` with no file argument runs the project (Main().main()).
    ran = _tawlac(["run"], cwd=proj)
    assert ran.returncode == 0
    assert ran.stdout == "Hello, Tawla!\n"


def test_init_in_current_dir_then_run(tmp_path):
    assert _tawlac(["init"], cwd=tmp_path).returncode == 0
    ran = _tawlac(["run"], cwd=tmp_path)
    assert ran.stdout == "Hello, Tawla!\n"


def test_run_without_project_fails(tmp_path):
    # No Tawla.toml anywhere up the tree -> non-zero exit.
    assert _tawlac(["run"], cwd=tmp_path).returncode != 0
