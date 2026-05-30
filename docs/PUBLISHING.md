# Publishing Tawla to PyPI

Once it's on PyPI, anyone can install the compiler with `pipx install tawla`
(or `pip install tawla`) on any OS. Here's the process.

## 1. Finish the metadata

Open `pyproject.toml` and fill in the TODOs: a **license** (PyPI strongly
recommends one — e.g. `license = "MIT"`), `authors`, and a `[project.urls]`
section. Bump `version` here and in `tawla/__init__.py` for every release (they
should match).

## 2. Build the distribution

```
pip install build twine
python -m build
```

This creates `dist/tawla-<version>.tar.gz` (sdist) and a `.whl` (wheel).

## 3. (Optional but recommended) try TestPyPI first

```
twine upload --repository testpypi dist/*
pipx install --index-url https://test.pypi.org/simple/ tawla
```

## 4. Upload to the real PyPI

```
twine upload dist/*
```

You'll need a PyPI account and an API token. After this, `pipx install tawla`
works for everyone.

## Notes

- The name `tawla` has to be free on PyPI — check https://pypi.org/project/tawla/
  before you publish.
- `llvmlite` is an ordinary dependency; pip fetches its prebuilt wheel
  automatically on Windows, macOS, and Linux (x86-64 and arm64), so users don't
  build LLVM themselves.
- Until you publish, people can still install straight from source:
  `pipx install git+<your-repo-url>`.
