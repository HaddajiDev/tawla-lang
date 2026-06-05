# Python-free, PATH-installable `tawlac` Binaries — Design

## Goal

Let a user with **no Python installed** download a single `tawlac` binary for
their operating system, put it on their `PATH`, and run `tawlac run app.twl`,
`tawlac new`, `tawlac init`, etc. directly — exactly like the pip-installed
command. `pip install tawla` remains available as an additional install path
(this work is additive, not a replacement).

## Why this works

The Tawla compiler is pure Python and JITs programs in-process via `llvmlite`,
with runtime support functions (`gc_*`, IO, strings, HTTP, fetch) hosted in
Python and registered through `llvm.add_symbol`. We are **not** changing any of
that. Instead we package the whole thing — CPython, `llvmlite` (including its
native LLVM shared library), the compiler, and the bundled stdlib `.twl` files —
into one self-contained executable using **PyInstaller**. Python still runs
*inside* the binary; the user never installs or sees it.

This is a packaging/distribution change plus one small code fix, not a compiler
rewrite.

## Components

### 1. `tawlac.spec` (committed PyInstaller spec)

A reproducible spec file at the repo root. Key settings:

- **One-file** console binary (`onefile`, `console=True`) named `tawlac`.
- **Entry point**: a dedicated launcher `pyinstaller_entry.py` at the repo root
  containing exactly:
  ```python
  import sys
  from tawla.cli import main
  sys.exit(main())
  ```
  (A dedicated script, rather than `tawla/__main__.py`, avoids any reliance on
  the `if __name__ == "__main__"` guard inside the frozen entry.)
- **Bundled stdlib**: `datas=[('tawla/stdlib', 'tawla/stdlib')]` so the runtime
  `.twl` modules (IO, Collections, Json, Http) ship inside the binary.
- **LLVM library**: collect llvmlite's native binding so the JIT works in the
  frozen app. Achieved via `collect_all('llvmlite')` in the spec (equivalent to
  the `--collect-all llvmlite` CLI flag) feeding `datas`/`binaries`/
  `hiddenimports`.
- **hiddenimports**: explicitly list the runtime modules that are wired through
  `llvm.add_symbol` rather than ordinary call sites, to guarantee inclusion:
  `tawla.gc_runtime`, `tawla.io_runtime`, `tawla.http_runtime`,
  `tawla.fetch_runtime`, `tawla.str_runtime`. (PyInstaller's static analysis
  already follows the imports in `compiler.py`; this is belt-and-suspenders.)

### 2. Frozen-path fix in `tawla/loader.py`

Today: `STDLIB_DIR = Path(__file__).resolve().parent / "stdlib"`.

Under a PyInstaller one-file build, modules are extracted to a temp dir exposed
as `sys._MEIPASS`. Change the resolution to:

```python
import sys
from pathlib import Path

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    STDLIB_DIR = Path(sys._MEIPASS) / "tawla" / "stdlib"
else:
    STDLIB_DIR = Path(__file__).resolve().parent / "stdlib"
```

This keeps the pip-installed path unchanged and adds a correct frozen path. The
`datas` target in the spec (`tawla/stdlib`) matches this `_MEIPASS/tawla/stdlib`
location.

### 3. `.github/workflows/release.yml`

Triggered on pushing a tag matching `v*`. A build matrix over
`windows-latest`, `macos-latest`, `ubuntu-latest`:

1. Checkout, set up Python (3.11+).
2. `pip install -e .` and `pip install pyinstaller`.
3. `pyinstaller tawlac.spec` (produces `dist/tawlac` or `dist/tawlac.exe`).
4. **Smoke test the built binary** (see Verification).
5. Rename per-OS (`tawlac-windows.exe`, `tawlac-macos`, `tawlac-linux`) and
   upload to the GitHub Release for that tag (using `softprops/action-gh-release`
   or `gh release upload`).

The workflow needs `contents: write` permission to attach release assets.

### 4. Docs + README

Add a "Download — no Python required" section to both `README.md` and the docs
site (`tawla_lang_docs/index.html`, install area), with per-OS **Add-to-PATH**
instructions, kept beside the existing `pip install tawla` instructions:

- **Windows**: download `tawlac.exe`, place in e.g. `C:\tools\tawla`, add that
  folder to the `Path` environment variable; `tawlac` then works in any
  terminal.
- **macOS / Linux**: download `tawlac`, `chmod +x tawlac`, move to a PATH dir
  (`/usr/local/bin`) or `export PATH="$PATH:/path/to/dir"` in
  `~/.bashrc` / `~/.zshrc`.
- Note for macOS: the binary is unsigned, so first run may require allowing it
  in System Settings → Privacy & Security (or `xattr -d com.apple.quarantine
  tawlac`).

## Verification

The real proof that the binary is Python-free is **running the built binary
itself** — it uses its embedded interpreter, not system Python. Smoke tests
(run in CI on each OS, and locally on Windows before tagging):

- `./tawlac version` prints `tawlac <version>`.
- `./tawlac run examples/hello.twl` prints `Hello, Tawla!`.
- A run exercising the bundled stdlib (e.g. a small program that
  `import "Collections.twl";` and prints a list size) to confirm the stdlib is
  bundled and the frozen path resolves.

If a smoke test fails in CI, the release asset for that OS is not produced and
the workflow fails loudly.

## Scope

**In scope, now:**
- `tawlac.spec`, the `loader.py` frozen-path fix, the 3-OS CI workflow, and the
  docs/README updates.
- Build and verify the **Windows** binary locally this session (we are on
  Windows). macOS and Linux binaries are produced and smoke-tested by CI on the
  next tagged release; they cannot be run locally here.

**Out of scope:**
- `tawlac build` — emitting native standalone *programs* (the separate
  "Track A" effort). Unrelated to making the compiler Python-free.
- A one-line installer script (curl | sh / PowerShell). Manual PATH
  instructions only for now.
- Code signing / notarization of the macOS and Windows binaries.

## Risks / notes

- **llvmlite bundling** is the main technical risk: its native LLVM library must
  be collected. `collect_all('llvmlite')` handles this in practice; the local
  Windows build verifies it before we rely on CI.
- **Binary size**: bundling CPython + LLVM yields a large binary (tens of MB).
  Acceptable for a downloadable compiler.
- **Per-OS builds** must run on their own OS — hence the GitHub Actions matrix.
- The dev **test suite is unaffected** (`tests/conftest.py` invokes
  `sys.executable -m tawla` for development; the shipped binary does not depend
  on that path).
