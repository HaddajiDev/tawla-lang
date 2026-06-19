"""M40: API ergonomics — string interpolation + toJson()."""


def test_tostring_universal(run_twl):
    src = (
        "class Main { void main() {"
        ' print(toString("x")); print(toString(true)); print(toString(false));'
        " print(toString(42)); print(toString(1.5)); } }"
    )
    assert run_twl(src).stdout == "x\ntrue\nfalse\n42\n1.5\n"
