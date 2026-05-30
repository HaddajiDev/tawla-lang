"""Stitches a multi-file program into one flat list of items.

An `import "other.twl";` says "go read that file and pull its declarations in
here." This module walks those imports starting from an entry file (or an
already-parsed chunk of source), reads each imported file once, and hands back a
single list of items with every Import expanded away. After this runs, the rest
of the pipeline (monomorphize -> sema -> codegen) never has to think about files.

Paths in an import are relative to the file doing the importing. If you leave off
the `.twl`, we add it for you, so `import "math";` and `import "math.twl";` mean
the same thing. A file is only ever loaded once even if several files import it,
and import cycles are fine (we just stop when we come back around).

Imported files can only hold declarations — classes, interfaces, and functions.
Loose top-level statements (the script-style body, the thing that becomes the
program's entry point) only make sense in the file you actually run, so we say no
to them anywhere else.
"""

from pathlib import Path

from .ast_nodes import ClassDecl, FuncDecl, Import, InterfaceDecl
from .lexer import tokenize
from .parser import parse

_DECLS = (ClassDecl, InterfaceDecl, FuncDecl)


class LoadError(Exception):
    pass


def load_program(entry) -> list:
    """Load the program rooted at `entry` (a path to a `.twl` file), following
    every import, and return the merged list of items."""
    entry = Path(entry).resolve()
    try:
        src = entry.read_text(encoding="utf-8")
    except OSError as e:
        raise LoadError(f"cannot read {entry}: {e}") from e
    out: list = []
    _expand(parse(tokenize(src)), entry.parent, True, {entry}, out)
    return out


def resolve_imports(items: list, base_dir) -> list:
    """Expand the imports inside an already-parsed list of items, resolving paths
    relative to `base_dir`. Used for source that didn't come from a file on disk."""
    out: list = []
    _expand(items, Path(base_dir).resolve(), True, set(), out)
    return out


def _expand(items: list, base_dir: Path, is_entry: bool, visited: set, out: list) -> None:
    for item in items:
        if isinstance(item, Import):
            target = _resolve(base_dir, item.path)
            if target in visited:
                continue
            visited.add(target)
            try:
                src = target.read_text(encoding="utf-8")
            except OSError as e:
                raise LoadError(f"cannot read imported file {target}: {e}") from e
            _expand(parse(tokenize(src)), target.parent, False, visited, out)
        elif is_entry or isinstance(item, _DECLS):
            out.append(item)
        else:
            raise LoadError(
                "imported files can only contain class, interface, and function "
                "declarations — move loose statements into the file you run"
            )


def _resolve(base_dir: Path, raw: str) -> Path:
    path = Path(raw)
    if not path.suffix:
        path = path.with_suffix(".twl")
    target = (base_dir / path).resolve()
    if not target.is_file():
        raise LoadError(f"cannot find imported file {raw!r} (looked for {target})")
    return target
