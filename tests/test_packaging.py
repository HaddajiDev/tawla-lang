"""Smoke program used by the release pipeline; also guards that the loader's
stdlib resolution keeps working in the normal (non-frozen) interpreter."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_smoke_example_runs(run_twl):
    src = (ROOT / "examples" / "smoke.twl").read_text(encoding="utf-8")
    assert run_twl(src).stdout == "2\n8\nz\n"
