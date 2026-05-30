"""The tokens — the little building blocks the lexer spits out and the parser reads."""

from dataclasses import dataclass
from enum import Enum, auto


class TokenKind(Enum):
    INT = auto()
    STRING = auto()
    IDENT = auto()
    KW_INT = auto()
    KW_BOOL = auto()
    KW_STRING = auto()
    KW_VOID = auto()
    KW_VAR = auto()
    KW_PRINT = auto()
    KW_IF = auto()
    KW_ELSE = auto()
    KW_WHILE = auto()
    KW_TRUE = auto()
    KW_FALSE = auto()
    KW_RETURN = auto()
    KW_CLASS = auto()
    KW_NEW = auto()
    KW_THIS = auto()
    KW_INTERFACE = auto()
    KW_ABSTRACT = auto()
    KW_SUPER = auto()
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    LT = auto()
    GT = auto()
    LE = auto()
    GE = auto()
    EQ = auto()
    NE = auto()
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    ASSIGN = auto()
    SEMICOLON = auto()
    COMMA = auto()
    DOT = auto()
    COLON = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    EOF = auto()


KEYWORDS = {
    "int": TokenKind.KW_INT,
    "bool": TokenKind.KW_BOOL,
    "string": TokenKind.KW_STRING,
    "void": TokenKind.KW_VOID,
    "var": TokenKind.KW_VAR,
    "print": TokenKind.KW_PRINT,
    "if": TokenKind.KW_IF,
    "else": TokenKind.KW_ELSE,
    "while": TokenKind.KW_WHILE,
    "true": TokenKind.KW_TRUE,
    "false": TokenKind.KW_FALSE,
    "return": TokenKind.KW_RETURN,
    "class": TokenKind.KW_CLASS,
    "new": TokenKind.KW_NEW,
    "this": TokenKind.KW_THIS,
    "interface": TokenKind.KW_INTERFACE,
    "abstract": TokenKind.KW_ABSTRACT,
    "super": TokenKind.KW_SUPER,
}


@dataclass
class Token:
    kind: TokenKind
    text: str | None = None
    pos: int = 0
