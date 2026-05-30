"""Lexer: turns raw source text into a flat list of tokens.

One left-to-right pass. We skip whitespace, group runs of digits into one INT,
read words into keywords or identifiers, handle string literals, and map the
operators. Anything we don't recognize is a lexical error.
"""

from .tokens import KEYWORDS, Token, TokenKind

_SINGLE = {
    "+": TokenKind.PLUS,
    "-": TokenKind.MINUS,
    "*": TokenKind.STAR,
    "/": TokenKind.SLASH,
    "(": TokenKind.LPAREN,
    ")": TokenKind.RPAREN,
    "{": TokenKind.LBRACE,
    "}": TokenKind.RBRACE,
    ";": TokenKind.SEMICOLON,
    ",": TokenKind.COMMA,
    ".": TokenKind.DOT,
    ":": TokenKind.COLON,
    "[": TokenKind.LBRACKET,
    "]": TokenKind.RBRACKET,
}


def _is_ident_start(c: str) -> bool:
    return c.isalpha() or c == "_"


def _is_ident_part(c: str) -> bool:
    return c.isalnum() or c == "_"


class LexError(Exception):
    pass


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "0": "\0"}
_BOM = chr(0xFEFF)


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(src)

    while i < n:
        c = src[i]

        if c.isspace() or c == _BOM:
            i += 1
            continue

        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue

        if c.isdigit():
            start = i
            while i < n and src[i].isdigit():
                i += 1
            tokens.append(Token(TokenKind.INT, src[start:i], start))
            continue

        if _is_ident_start(c):
            start = i
            while i < n and _is_ident_part(src[i]):
                i += 1
            word = src[start:i]
            kind = KEYWORDS.get(word, TokenKind.IDENT)
            tokens.append(Token(kind, word, start))
            continue

        if c == '"':
            start = i
            i += 1
            chars: list[str] = []
            while i < n and src[i] != '"':
                if src[i] == "\\":
                    i += 1
                    if i >= n:
                        raise LexError(f"unterminated escape in string at position {start}")
                    esc = _ESCAPES.get(src[i])
                    if esc is None:
                        raise LexError(f"unknown escape '\\{src[i]}' at position {i}")
                    chars.append(esc)
                else:
                    chars.append(src[i])
                i += 1
            if i >= n:
                raise LexError(f"unterminated string literal at position {start}")
            i += 1
            tokens.append(Token(TokenKind.STRING, "".join(chars), start))
            continue

        nxt = src[i + 1] if i + 1 < n else ""
        if c == "=":
            kind, text = (TokenKind.EQ, "==") if nxt == "=" else (TokenKind.ASSIGN, "=")
        elif c == "<":
            kind, text = (TokenKind.LE, "<=") if nxt == "=" else (TokenKind.LT, "<")
        elif c == ">":
            kind, text = (TokenKind.GE, ">=") if nxt == "=" else (TokenKind.GT, ">")
        elif c == "!":
            if nxt != "=":
                raise LexError(f"unexpected character '!' at position {i}")
            kind, text = TokenKind.NE, "!="
        else:
            kind = text = None

        if kind is not None:
            tokens.append(Token(kind, text, i))
            i += len(text)
            continue

        if c in _SINGLE:
            tokens.append(Token(_SINGLE[c], c, i))
            i += 1
            continue

        raise LexError(f"unexpected character {c!r} at position {i}")

    tokens.append(Token(TokenKind.EOF, None, i))
    return tokens
