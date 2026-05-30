"""M15: `//` line comments."""

from tawla.lexer import tokenize
from tawla.tokens import TokenKind


def test_comment_is_skipped():
    kinds = [t.kind for t in tokenize("1 + 2 // this is ignored\n+ 3")]
    assert kinds == [
        TokenKind.INT, TokenKind.PLUS, TokenKind.INT,
        TokenKind.PLUS, TokenKind.INT, TokenKind.EOF,
    ]


def test_comment_to_end_of_input():
    assert [t.kind for t in tokenize("42 // trailing")] == [TokenKind.INT, TokenKind.EOF]


def test_full_line_comment(run_twl):
    src = "// header comment\nprint(7); // inline\n// footer"
    assert run_twl(src).stdout == "7\n"


def test_division_still_works(run_twl):
    # A single '/' is still division; only '//' starts a comment.
    assert run_twl("print(10 / 2);").stdout == "5\n"
