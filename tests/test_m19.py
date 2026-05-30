"""M19: garbage collection — conservative mark-sweep with precise roots."""

from tawla.compiler import run_source
from tawla.sema import SemaError
import pytest

BOX = "class Box { int v; Box(int v) { this.v = v; } int get() { return this.v; } } "
WASTE = "void waste() { var x = new Box(0); } "


def test_garbage_is_reclaimed(run_twl):
    src = BOX + WASTE + (
        "int i = 0; while (i < 10) { waste(); i = i + 1; } "
        "print(__live()); collect(); print(__live());"
    )
    assert run_twl(src).stdout == "10\n0\n"


def test_live_object_survives_and_is_valid(run_twl):
    src = BOX + WASTE + (
        "var keep = new Box(42); "
        "int i = 0; while (i < 10) { waste(); i = i + 1; } "
        "collect(); print(__live()); print(keep.get());"
    )
    assert run_twl(src).stdout == "1\n42\n"


def test_reachable_through_field_survives(run_twl):
    # `a` is a root; `a.next` is reachable only through a's field. Conservative
    # interior scanning must keep both alive.
    src = (
        "class Node { Node next; int v; Node(int v) { this.v = v; } } "
        + WASTE.replace("Box", "Node")
        + "var a = new Node(1); a.next = new Node(2); "
        + "int i = 0; while (i < 5) { waste(); i = i + 1; } "
        + "collect(); print(__live()); print(a.next.v);"
    )
    assert run_twl(src).stdout == "2\n2\n"


def test_collect_with_nothing_live(run_twl):
    src = BOX + WASTE + (
        "int i = 0; while (i < 7) { waste(); i = i + 1; } "
        "collect(); print(__live());"
    )
    assert run_twl(src).stdout == "0\n"


def test_program_correctness_unaffected_by_gc(run_twl):
    # A normal computation interleaved with collections still produces the
    # right answer (no premature frees corrupting live data).
    src = (
        "class Counter { int n; Counter() { this.n = 0; } "
        "void add(int x) { this.n = this.n + x; } int get() { return this.n; } } "
        "var c = new Counter(); int i = 1; "
        "while (i <= 100) { c.add(i); collect(); i = i + 1; } "
        "print(c.get());"
    )
    assert run_twl(src).stdout == "5050\n"


def test_collect_takes_no_args():
    with pytest.raises(SemaError):
        run_source("collect(1);")
