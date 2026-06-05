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
