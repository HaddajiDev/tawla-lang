"""Cargo-style projects: the `Tawla.toml` file and the `tawlac new` scaffolding.

A Tawla project is just a folder with a `Tawla.toml` and a `src/` directory.
`tawlac run` (with no file given) walks up from wherever you are until it finds
the manifest, reads which file is the entry point, and runs that.
"""

import tomllib
from pathlib import Path

MANIFEST = "Tawla.toml"
DEFAULT_ENTRY = "src/main.twl"

_MANIFEST_TEMPLATE = """\
[package]
name = "{name}"
version = "0.0.0"

[build]
entry = "{entry}"
"""

_MAIN_TEMPLATE = """\
class Main {
    void main() {
        print("Hello, Tawla!");
    }
}
"""


class ProjectError(Exception):
    pass


def find_manifest(start: Path) -> Path:
    """Look for `Tawla.toml` here, then keep walking up the folders until we hit it."""
    start = start.resolve()
    for directory in (start, *start.parents):
        candidate = directory / MANIFEST
        if candidate.is_file():
            return candidate
    raise ProjectError(f"no {MANIFEST} found in {start} or any parent directory")


def entry_path(manifest: Path) -> Path:
    """Read the manifest and work out which file is the entry point."""
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    entry = data.get("build", {}).get("entry", DEFAULT_ENTRY)
    return manifest.parent / entry


def scaffold(root: Path, name: str) -> None:
    """Drop a fresh project (the manifest + src/main.twl) into `root`."""
    manifest = root / MANIFEST
    if manifest.exists():
        raise ProjectError(f"{MANIFEST} already exists in {root}")
    (root / "src").mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        _MANIFEST_TEMPLATE.format(name=name, entry=DEFAULT_ENTRY), encoding="utf-8"
    )
    (root / DEFAULT_ENTRY).write_text(_MAIN_TEMPLATE, encoding="utf-8")
