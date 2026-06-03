"""M33: JSON write (builders, toString, respondJson) + Map.keys."""

import http.client
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_map_keys(run_twl):
    src = (
        'import "Collections.twl";'
        " class Main { void main() {"
        ' Map<string, int> m = new Map<string, int>();'
        ' m.put("a", 1); m.put("b", 2); m.put("c", 3);'
        " List<string> ks = m.keys();"
        " print(ks.size()); print(ks.get(0)); print(ks.get(2)); } }"
    )
    assert run_twl(src).stdout == "3\na\nc\n"
