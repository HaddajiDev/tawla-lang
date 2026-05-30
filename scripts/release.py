"""Cut a new Tawla release: bump the version, rebuild, and upload to PyPI.

Run it with the project's virtualenv Python (so `build` and `twine` are available):

    venv\\Scripts\\python scripts/release.py 0.1.1     # Windows
    venv/bin/python scripts/release.py 0.1.1          # Linux / macOS

It bumps the version in both pyproject.toml and tawla/__init__.py, wipes old
build output, builds the sdist + wheel, validates them, asks you to confirm, and
then uploads. twine will prompt for your PyPI token (username: __token__).
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "tawla" / "__init__.py"


def fail(msg: str) -> None:
    print(f"error: {msg}")
    raise SystemExit(1)


def bump(path: Path, pattern: str, version: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, rf"\g<1>{version}\g<2>", text, count=1)
    if count != 1:
        fail(f"couldn't find the version line in {label}")
    path.write_text(new_text, encoding="utf-8")


def run(*cmd: str) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: python scripts/release.py <version>   e.g. 0.1.1")
    version = sys.argv[1]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        fail(f"'{version}' doesn't look like X.Y.Z")

    current = re.search(r'(?m)^version = "([^"]+)"', PYPROJECT.read_text(encoding="utf-8"))
    if current and current.group(1) == version:
        fail(f"version is already {version}; PyPI won't accept a re-upload — pick a new one")

    bump(PYPROJECT, r'(?m)(^version = ")[^"]+(")', version, "pyproject.toml")
    bump(INIT, r'(__version__ = ")[^"]+(")', version, "tawla/__init__.py")
    print(f"bumped version to {version}")

    for directory in ("dist", "build"):
        shutil.rmtree(ROOT / directory, ignore_errors=True)

    run(sys.executable, "-m", "build")
    artifacts = sorted(str(p) for p in (ROOT / "dist").glob("*"))
    run(sys.executable, "-m", "twine", "check", *artifacts)

    print("\nabout to upload to PyPI:")
    for a in artifacts:
        print("   ", Path(a).name)
    if input("continue? [y/N] ").strip().lower() != "y":
        print("stopped before upload. (the version files are already bumped to "
              f"{version} — commit or revert them as you like)")
        return

    run(sys.executable, "-m", "twine", "upload", *artifacts)
    print(f"\ntawla {version} is live: https://pypi.org/project/tawla/{version}/")
    print("don't forget to commit + tag the release:")
    print(f'    git commit -am "Release {version}" && git tag v{version} && git push --tags')


if __name__ == "__main__":
    main()
