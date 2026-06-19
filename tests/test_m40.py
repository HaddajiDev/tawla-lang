"""M40: API ergonomics — string interpolation + toJson()."""


def test_tostring_universal(run_twl):
    src = (
        "class Main { void main() {"
        ' print(toString("x")); print(toString(true)); print(toString(false));'
        " print(toString(42)); print(toString(1.5)); } }"
    )
    assert run_twl(src).stdout == "x\ntrue\nfalse\n42\n1.5\n"


def test_interp_basic(run_twl):
    src = (
        "class Main { void main() {"
        ' string n = "Ada"; int x = 3;'
        ' print("hi ${n}, ${x + 1} items");'
        ' print("${true}|${1.5}|$5.00"); } }'
    )
    assert run_twl(src).stdout == "hi Ada, 4 items\ntrue|1.5|$5.00\n"


def test_interp_plain_and_escapes(run_twl):
    src = 'class Main { void main() { print("a\\tb"); print("no interp here"); } }'
    assert run_twl(src).stdout == "a\tb\nno interp here\n"
