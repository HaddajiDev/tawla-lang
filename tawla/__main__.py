"""Lets you run the CLI with `python -m tawla ...`."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
