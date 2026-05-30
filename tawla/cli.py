"""The `tawlac` command line — this is what runs when you type `tawlac ...`."""

import argparse
import sys
from pathlib import Path

from . import __version__
from .compiler import run_file
from .project import entry_path, find_manifest, scaffold


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="tawlac",
        description="The Tawla compiler",
        epilog="Run 'tawlac help <command>' for details on a command.",
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"tawlac {__version__}",
        help="show the tawlac version and exit",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    run_p = sub.add_parser("run", help="compile and run a .twl file or project (JIT)")
    run_p.add_argument(
        "file", nargs="?", type=Path,
        help="a .twl file; omit to run the project in the current directory",
    )

    build_p = sub.add_parser("build", help="emit a native binary (not implemented yet)")
    build_p.add_argument("file", nargs="?", type=Path, help="a .twl file")

    new_p = sub.add_parser("new", help="create a new project in a new directory")
    new_p.add_argument("name", help="project name (also the directory created)")

    sub.add_parser("init", help="create a project in the current directory")
    sub.add_parser("version", help="print the tawlac version")
    help_p = sub.add_parser("help", help="show help for tawlac or a command")
    help_p.add_argument("topic", nargs="?", help="a command to describe")

    return parser, sub


def main(argv=None) -> int:
    parser, sub = _build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "help"):
        topic = getattr(args, "topic", None)
        if topic and topic in sub.choices:
            sub.choices[topic].print_help()
        else:
            parser.print_help()
        return 0

    if args.command == "version":
        print(f"tawlac {__version__}")
        return 0
    if args.command == "run":
        return _run(args.file)
    if args.command == "build":
        return _build()
    if args.command == "new":
        return _new(args.name)
    if args.command == "init":
        return _init()
    parser.error(f"unknown command: {args.command}")
    return 2


def _build() -> int:
    print(
        "tawlac build isn't implemented yet. For now, run programs with "
        "'tawlac run' (they're JIT-compiled and run in memory). Emitting a "
        "standalone native binary is planned.",
        file=sys.stderr,
    )
    return 1


def _run(file: Path | None) -> int:
    if file is None:
        file = entry_path(find_manifest(Path.cwd()))
    return run_file(file)


def _new(name: str) -> int:
    root = Path(name)
    scaffold(root, name)
    print(f"Created project '{name}' (run it with: cd {name} && tawlac run)")
    return 0


def _init() -> int:
    root = Path.cwd()
    scaffold(root, root.name)
    print("Initialized project in the current directory (run it with: tawlac run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
