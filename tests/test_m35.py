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
