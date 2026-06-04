"""M35: increment/decrement operators (++ / --)."""

from tawla.lexer import tokenize
from tawla.tokens import TokenKind


def test_lexes_plusplus_and_minusminus():
    kinds = [t.kind for t in tokenize("++ -- + -")]
    assert kinds[:4] == [
        TokenKind.PLUS_PLUS,
        TokenKind.MINUS_MINUS,
        TokenKind.PLUS,
        TokenKind.MINUS,
    ]


def test_maximal_munch_no_spaces():
    # "i++" must lex as IDENT then PLUS_PLUS, not IDENT PLUS PLUS
    kinds = [t.kind for t in tokenize("i++")]
    assert kinds == [TokenKind.IDENT, TokenKind.PLUS_PLUS, TokenKind.EOF]


def test_postfix_increment_variable(run_twl):
    assert run_twl("int i = 0; i++; print(i);").stdout == "1\n"


def test_prefix_increment_variable(run_twl):
    assert run_twl("int i = 0; ++i; print(i);").stdout == "1\n"


def test_postfix_decrement_variable(run_twl):
    assert run_twl("int i = 5; i--; print(i);").stdout == "4\n"


def test_prefix_decrement_variable(run_twl):
    assert run_twl("int i = 5; --i; print(i);").stdout == "4\n"


def test_increment_array_element(run_twl):
    src = "int[] a = new int[3]; a[1] = 10; a[1]++; print(a[1]);"
    assert run_twl(src).stdout == "11\n"


def test_increment_float(run_twl):
    assert run_twl("float f = 1.5; f++; print(f);").stdout == "2.5\n"


def test_increment_object_field(run_twl):
    src = (
        "class Counter {"
        "    public int n;"
        "    public Counter() { this.n = 0; }"
        "    public void bump() { this.n++; }"
        "}"
        "class Main {"
        "    void main() {"
        "        Counter c = new Counter();"
        "        c.bump(); c.bump();"
        "        print(c.n);"
        "    }"
        "}"
    )
    assert run_twl(src).stdout == "2\n"


def test_longhand_still_works(run_twl):
    assert run_twl("int i = 5; i = i + 1; print(i);").stdout == "6\n"


def test_subtraction_and_unary_minus_still_lex(run_twl):
    # Guards that splitting +/- into the two-char chain didn't break single -.
    assert run_twl("int a = 10 - 3; print(a);").stdout == "7\n"
    assert run_twl("int b = 0 - 5; print(b);").stdout == "-5\n"


def test_for_loop_postfix_step(run_twl):
    src = "for (int i = 0; i < 3; i++) { print(i); }"
    assert run_twl(src).stdout == "0\n1\n2\n"


def test_for_loop_prefix_step(run_twl):
    src = "for (int i = 0; i < 3; ++i) { print(i); }"
    assert run_twl(src).stdout == "0\n1\n2\n"


def test_for_loop_decrement_step(run_twl):
    src = "for (int i = 3; i > 0; i--) { print(i); }"
    assert run_twl(src).stdout == "3\n2\n1\n"


def test_for_loop_postfix_init(run_twl):
    # init clause uses ++ too (handled by assign_or_expr_stmt)
    src = "int i = 0; for (i++; i < 3; i++) { print(i); }"
    assert run_twl(src).stdout == "1\n2\n"
