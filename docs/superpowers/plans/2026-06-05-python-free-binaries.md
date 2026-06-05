# Python-free, PATH-installable `tawlac` Binaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `tawlac` as a self-contained per-OS executable (no Python install needed) that users drop on their PATH, built by CI on tagged releases.

**Architecture:** PyInstaller packs CPython + `llvmlite` + the compiler + the bundled stdlib `.twl` files into one binary. The compiler is unchanged; only the stdlib path resolution gains a frozen-bundle branch. A GitHub Actions matrix builds and smoke-tests the binary on Windows/macOS/Linux and attaches it to the GitHub Release. `pip install tawla` stays.

**Tech Stack:** Python 3.11+, PyInstaller, llvmlite, GitHub Actions, pytest.

**Reference spec:** `docs/superpowers/specs/2026-06-05-python-free-binaries-design.md`

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `tawla/loader.py` | stdlib path resolution | Add frozen (`sys._MEIPASS`) branch |
| `examples/smoke.twl` | release smoke-test program (exercises stdlib) | New |
| `tests/test_packaging.py` | regression guard for the smoke program | New |
| `pyinstaller_entry.py` | PyInstaller entry script | New (repo root) |
| `tawlac.spec` | PyInstaller build recipe | New (repo root) |
| `pyproject.toml` | optional `build` extra for pyinstaller | Add `[project.optional-dependencies]` |
| `.github/workflows/release.yml` | CI: build + smoke + upload per OS | New |
| `README.md` | "Download — no Python required" + Add-to-PATH | New section |
| `tawla_lang_docs/index.html` | same, on the docs site (separate repo) | New block in install area |

Known facts (verified):
- `examples/hello.twl` is `int x = 5; print(x * 2);` → prints `10`.
- `build/` and `dist/` are already in `.gitignore`.
- `tawla/loader.py` currently: `STDLIB_DIR = Path(__file__).resolve().parent / "stdlib"` (line ~30); it imports only `from pathlib import Path` — `import sys` must be added.
- List API (from `Collections.twl`): `new List<int>()`, `.add(x)`, `.size()`, `.get(i)`.
- Current version: `1.4.0`.

---

## Task 1: Frozen-path fix + smoke-test program

**Files:**
- Modify: `tawla/loader.py` (imports; `STDLIB_DIR` definition ~line 30)
- Create: `examples/smoke.twl`
- Create: `tests/test_packaging.py`

- [ ] **Step 1: Create the smoke-test program**

Create `examples/smoke.twl`:

```tawla
// Release smoke test: exercises the bundled standard library so a built
// binary proves it can find and run stdlib modules (frozen-path resolution).
import "Collections.twl";

class Main {
    void main() {
        List<int> xs = new List<int>();
        xs.add(7);
        xs.add(8);
        print(xs.size());      // 2
        print(xs.get(1));      // 8
    }
}
```

- [ ] **Step 2: Verify it runs under the normal interpreter**

Run: `venv/Scripts/python.exe -m tawla run examples/smoke.twl`
Expected output:
```
2
8
```

- [ ] **Step 3: Write the regression test**

Create `tests/test_packaging.py`:

```python
"""Smoke program used by the release pipeline; also guards that the loader's
stdlib resolution keeps working in the normal (non-frozen) interpreter."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_smoke_example_runs(run_twl):
    src = (ROOT / "examples" / "smoke.twl").read_text(encoding="utf-8")
    assert run_twl(src).stdout == "2\n8\n"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_packaging.py -v`
Expected: PASS (the loader is unchanged so far; this guards the next step).

- [ ] **Step 5: Add the frozen-bundle branch to the loader**

In `tawla/loader.py`, change the import line `from pathlib import Path` to add `sys`:

```python
import sys
from pathlib import Path
```

Then replace the `STDLIB_DIR` definition:

```python
STDLIB_DIR = Path(__file__).resolve().parent / "stdlib"
```

with:

```python
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    # PyInstaller one-file bundle: stdlib is extracted under _MEIPASS/tawla/stdlib
    STDLIB_DIR = Path(sys._MEIPASS) / "tawla" / "stdlib"
else:
    STDLIB_DIR = Path(__file__).resolve().parent / "stdlib"
```

- [ ] **Step 6: Run the full suite (non-frozen path must be unchanged)**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass (412 + the new smoke test = 413).

- [ ] **Step 7: Commit**

```bash
git add tawla/loader.py examples/smoke.twl tests/test_packaging.py
git commit -m "Add stdlib frozen-path branch and release smoke example"
```

---

## Task 2: PyInstaller entry, spec, and local Windows build

**Files:**
- Create: `pyinstaller_entry.py` (repo root)
- Create: `tawlac.spec` (repo root)
- Modify: `pyproject.toml` (add optional `build` extra)

- [ ] **Step 1: Create the entry script**

Create `pyinstaller_entry.py` at the repo root:

```python
"""PyInstaller entry point: launch the tawlac CLI."""

import sys

from tawla.cli import main

sys.exit(main())
```

- [ ] **Step 2: Create the PyInstaller spec**

Create `tawlac.spec` at the repo root:

```python
# -*- mode: python ; coding: utf-8 -*-
# Builds a one-file, self-contained `tawlac` binary (no Python install needed).
from PyInstaller.utils.hooks import collect_all

# Pull in llvmlite's native LLVM library + data + submodules.
datas, binaries, hiddenimports = collect_all("llvmlite")

# Bundle the standard-library .twl modules under tawla/stdlib in the binary.
datas += [("tawla/stdlib", "tawla/stdlib")]

# Runtime modules are wired via llvm.add_symbol; list them explicitly so they
# are always included even if static analysis misses an indirect import.
hiddenimports += [
    "tawla.gc_runtime",
    "tawla.io_runtime",
    "tawla.http_runtime",
    "tawla.fetch_runtime",
    "tawla.str_runtime",
]

a = Analysis(
    ["pyinstaller_entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="tawlac",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
```

- [ ] **Step 3: Add an optional build extra to pyproject**

In `pyproject.toml`, add this section (place it right after the `dependencies = [...]` line in `[project]`, or as a new top-level table if `[project.optional-dependencies]` does not already exist):

```toml
[project.optional-dependencies]
build = ["pyinstaller>=6"]
```

- [ ] **Step 4: Install PyInstaller into the venv**

Run: `venv/Scripts/python.exe -m pip install "pyinstaller>=6"`
Expected: installs successfully.

- [ ] **Step 5: Build the binary**

Run: `venv/Scripts/pyinstaller.exe tawlac.spec --clean --noconfirm`
Expected: ends with `Building EXE ... completed successfully`, producing `dist/tawlac.exe`.

- [ ] **Step 6: Smoke-test the built binary (this is the real verification)**

Run each and check output:

```bash
./dist/tawlac.exe version
./dist/tawlac.exe run examples/hello.twl
./dist/tawlac.exe run examples/smoke.twl
```

Expected:
```
tawlac 1.4.0
10
2
8
```

If `version` works but `run examples/smoke.twl` fails to find `Collections.twl`, the frozen-path branch (Task 1) or the `datas` mapping is wrong — fix before continuing.

- [ ] **Step 7: Commit**

```bash
git add pyinstaller_entry.py tawlac.spec pyproject.toml
git commit -m "Add PyInstaller spec + entry for standalone tawlac binary"
```

(`dist/` and `build/` are gitignored, so the binary itself is not committed.)

---

## Task 3: GitHub Actions release workflow

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/release.yml`:

```yaml
name: Release binaries

on:
  push:
    tags:
      - "v*"

permissions:
  contents: write

jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: windows-latest
            bin: dist/tawlac.exe
            asset: tawlac-windows.exe
          - os: macos-latest
            bin: dist/tawlac
            asset: tawlac-macos
          - os: ubuntu-latest
            bin: dist/tawlac
            asset: tawlac-linux
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install
        run: python -m pip install -e . "pyinstaller>=6"

      - name: Build
        run: pyinstaller tawlac.spec --clean --noconfirm

      - name: Smoke test
        shell: bash
        run: |
          BIN="${{ matrix.bin }}"
          "$BIN" version | grep -q "tawlac"
          "$BIN" run examples/hello.twl | tr -d '\r' | grep -xq "10"
          "$BIN" run examples/smoke.twl | tr -d '\r' | tr '\n' ' ' | grep -q "2 8"

      - name: Stage asset
        shell: bash
        run: cp "${{ matrix.bin }}" "${{ matrix.asset }}"

      - name: Upload to release
        uses: softprops/action-gh-release@v2
        with:
          files: ${{ matrix.asset }}
```

- [ ] **Step 2: Validate the YAML parses**

Run:
```bash
venv/Scripts/python.exe -m pip install pyyaml -q
venv/Scripts/python.exe -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); print('valid yaml')"
```
Expected: `valid yaml`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "Add CI workflow to build and release per-OS tawlac binaries"
```

---

## Task 4: Docs and README — download + Add-to-PATH

**Files:**
- Modify: `README.md` (after the existing "Getting it running" / `pip install` area)
- Modify: `tawla_lang_docs/index.html` (install section; separate repo)

- [ ] **Step 1: Add a README section**

In `README.md`, immediately after the paragraph that ends with the `pip install tawla` block and its "Works the same on Windows, macOS, and Linux." line, insert:

```markdown
### No Python? Download a standalone binary

Each release also ships a self-contained `tawlac` that bundles everything it
needs — no Python install required. Grab the one for your OS from the
[Releases page](https://github.com/HaddajiDev/tawla-lang/releases) and put it on
your `PATH`:

- **Windows:** download `tawlac-windows.exe`, rename it to `tawlac.exe`, move it
  into a folder such as `C:\tools\tawla`, then add that folder to your `Path`
  environment variable (Settings → "Edit the system environment variables" →
  Environment Variables → edit `Path`). Open a new terminal and run `tawlac`.
- **macOS:** download `tawlac-macos`, then:
  ```
  mv tawlac-macos tawlac
  chmod +x tawlac
  sudo mv tawlac /usr/local/bin/
  ```
  First launch may be blocked because the binary is unsigned — allow it under
  System Settings → Privacy & Security, or run
  `xattr -d com.apple.quarantine /usr/local/bin/tawlac`.
- **Linux:** download `tawlac-linux`, then:
  ```
  mv tawlac-linux tawlac
  chmod +x tawlac
  sudo mv tawlac /usr/local/bin/
  ```

Then `tawlac run app.twl` works from anywhere, exactly like the pip version.
```

- [ ] **Step 2: Verify README renders sanely**

Run: `venv/Scripts/python.exe -c "p=open('README.md',encoding='utf-8').read(); assert 'standalone binary' in p and 'tawlac-windows.exe' in p; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Add the same to the docs site**

In `tawla_lang_docs/index.html`, in the `#install` section, after the existing
`pip install tawla` code block / closing of that block, add:

```html
      <h3>No Python? Download a standalone binary</h3>
      <p>Every release also ships a self-contained <code>tawlac</code> that bundles everything it needs — no Python required. Download the build for your OS from the <a href="https://github.com/HaddajiDev/tawla-lang/releases" target="_blank" rel="noopener">Releases page</a> and put it on your <code>PATH</code>:</p>
      <ul>
        <li><strong>Windows:</strong> download <code>tawlac-windows.exe</code>, rename it to <code>tawlac.exe</code>, drop it in a folder like <code>C:\tools\tawla</code>, and add that folder to your <code>Path</code> environment variable.</li>
        <li><strong>macOS / Linux:</strong> download the binary, then <code>mv tawlac-&lt;os&gt; tawlac &amp;&amp; chmod +x tawlac &amp;&amp; sudo mv tawlac /usr/local/bin/</code>. On macOS, first run may need approval under Privacy &amp; Security (unsigned binary).</li>
      </ul>
      <p>After that, <code>tawlac run app.twl</code> works from any terminal — same command as the pip version.</p>
```

(Place it before the closing `</section>` of `#install`. Match surrounding indentation.)

- [ ] **Step 4: Commit the compiler-repo README**

```bash
git add README.md
git commit -m "Document standalone binary download and PATH install"
```

- [ ] **Step 5: Commit and push the docs site (separate repo)**

```bash
cd D:\Projects\tawla_lang_docs
git add index.html
git commit -m "Document standalone binary download and PATH install"
git push
cd D:\Projects\Tawla_lang
```

---

## Task 5: Final verification and release note

**Files:** none (verification + release trigger)

- [ ] **Step 1: Run the full test suite one more time**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all pass (413).

- [ ] **Step 2: Re-confirm the built binary still smoke-tests**

Run:
```bash
./dist/tawlac.exe version
./dist/tawlac.exe run examples/smoke.twl
```
Expected: `tawlac 1.4.0`, then `2` and `8`.

- [ ] **Step 3: Release trigger (on user's go-ahead, not automatic)**

The CI workflow fires on a pushed `v*` tag. To cut the first binary release once
this is merged to `main` and pushed:

```bash
git tag v1.4.0
git push origin v1.4.0
```

This builds, smoke-tests, and attaches `tawlac-windows.exe`, `tawlac-macos`, and
`tawlac-linux` to the `v1.4.0` GitHub Release. (Creating/pushing the tag is a
deliberate release step — do it only when the user asks.)

---

## Done criteria

- `dist/tawlac.exe` runs `version`, `run examples/hello.twl` (→ `10`), and
  `run examples/smoke.twl` (→ `2`/`8`) on Windows with no reliance on system Python.
- `tawlac.spec`, `pyinstaller_entry.py`, the loader fix, the CI workflow, and the
  docs are committed; full pytest suite green.
- Pushing a `v*` tag produces smoke-tested Windows/macOS/Linux binaries on the
  GitHub Release.
- `pip install tawla` remains unaffected.
