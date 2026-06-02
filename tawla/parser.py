"""Parser: chews through the tokens and builds the AST, recursive-descent style.

The grammar's written out below, one rule per method. The nesting is what gives
us operator precedence for free: the deeper a rule sits, the tighter it binds, so
`*`/`/` end up beating `+`/`-` without any extra bookkeeping.

    program := item* EOF
    item    := import_decl | class_decl | func_decl | stmt
    import_decl := 'import' STRING ';'
    func_decl := type IDENT '(' params? ')' block
    params  := param (',' param)*
    param   := type IDENT
    type    := 'int' | 'float' | 'double' | 'bool' | IDENT   # IDENT = a class name

    class_decl := 'class' IDENT (':' IDENT)? '{' member* '}'
    member     := ctor | method | field
    ctor       := IDENT '(' params? ')' block  # IDENT == the class name
    method     := type IDENT '(' params? ')' block
    field      := type IDENT ';'

    stmt    := var_decl | assign | expr_stmt | print_stmt
             | if_stmt | while_stmt | return_stmt
    var_decl    := (type | 'var') IDENT '=' expr ';'
    assign      := lvalue '=' expr ';'          # lvalue = IDENT or field access
    expr_stmt   := expr ';'                      # e.g. a method call
    print_stmt  := 'print' '(' expr ')' ';'
    if_stmt     := 'if' '(' expr ')' block ('else' (if_stmt | block))?
    while_stmt  := 'while' '(' expr ')' block
    for_stmt    := 'for' '(' stmt? ';' expr? ';' step? ')' block
    step        := lvalue '=' expr | expr
    return_stmt := 'return' expr ';'
    block       := '{' stmt* '}'

    expr       := logic_or
    logic_or   := logic_and ('||' logic_and)*
    logic_and  := comparison ('&&' comparison)*
    comparison := additive (('<'|'>'|'<='|'>='|'=='|'!=') additive)?
    additive   := term (('+' | '-') term)*
    term       := factor (('*' | '/') factor)*
    factor     := ('-' | '!') factor | postfix
    postfix    := primary ('.' IDENT arglist? )*   # field access / method call
    primary    := INT | FLOAT | 'true' | 'false' | 'this' | 'new' IDENT arglist
                | IDENT arglist? | '(' expr ')'
    arglist    := '(' (expr (',' expr)*)? ')'
"""

from .ast_nodes import (
    Assign,
    BinaryOp,
    BoolLiteral,
    Call,
    ClassDecl,
    CtorDecl,
    Expr,
    ExprStmt,
    FieldAccess,
    FieldDecl,
    FloatLiteral,
    For,
    FuncDecl,
    Identifier,
    If,
    Import,
    Index,
    InterfaceDecl,
    IntLiteral,
    MethodCall,
    MethodDecl,
    MethodSig,
    New,
    NewArray,
    NullLiteral,
    Param,
    PrintStmt,
    Return,
    Stmt,
    StringLiteral,
    SuperCall,
    ThisExpr,
    UnaryOp,
    VarDecl,
    While,
)
from .tokens import Token, TokenKind

_COMPARISON_OPS = {
    TokenKind.LT,
    TokenKind.GT,
    TokenKind.LE,
    TokenKind.GE,
    TokenKind.EQ,
    TokenKind.NE,
}

_TYPE_TOKENS = {
    TokenKind.KW_INT, TokenKind.KW_FLOAT, TokenKind.KW_DOUBLE,
    TokenKind.KW_BOOL, TokenKind.KW_STRING, TokenKind.KW_VOID,
}

_VISIBILITY = {
    TokenKind.KW_PUBLIC: "public",
    TokenKind.KW_PROTECTED: "protected",
    TokenKind.KW_PRIVATE: "private",
}


class ParseError(Exception):
    pass


def _canon_type(name: str) -> str:
    """`double` is just a second spelling of `float`; fold it to one name so the
    rest of the compiler only ever deals with `float`."""
    return "float" if name == "double" else name


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind: TokenKind) -> Token:
        if self.current.kind is not kind:
            raise ParseError(
                f"expected {kind.name}, got {self.current.kind.name} "
                f"at position {self.current.pos}"
            )
        return self.advance()

    def peek(self, ahead: int = 1) -> Token:
        idx = min(self.pos + ahead, len(self.tokens) - 1)
        return self.tokens[idx]

    def type_name(self) -> str:
        """Consume a type and return its canonical string form. Handles type
        keywords/class names, generic args `Box<int>`, and `[]` array suffixes."""
        if self.current.kind in _TYPE_TOKENS or self.current.kind is TokenKind.IDENT:
            name = _canon_type(self.advance().text)
            if self.current.kind is TokenKind.LT:
                self.advance()
                args = [self.type_name()]
                while self.current.kind is TokenKind.COMMA:
                    self.advance()
                    args.append(self.type_name())
                self.expect(TokenKind.GT)
                name += "<" + ",".join(args) + ">"
            while self.current.kind is TokenKind.LBRACKET:
                self.advance()
                self.expect(TokenKind.RBRACKET)
                name += "[]"
            return name
        raise ParseError(
            f"expected a type, got {self.current.kind.name} "
            f"at position {self.current.pos}"
        )

    def type_name_base(self) -> str:
        """A base type name (no `[]`): a type keyword or a class/interface IDENT."""
        if self.current.kind in _TYPE_TOKENS or self.current.kind is TokenKind.IDENT:
            return _canon_type(self.advance().text)
        raise ParseError(
            f"expected a type, got {self.current.kind.name} at position {self.current.pos}"
        )

    def _is_decl_start(self) -> bool:
        """True when the upcoming tokens begin a declaration (not a statement).

        `int x`, `var x`, `ClassName x`, or `ClassName[] x`. A bare IDENT followed
        by `=`, `.`, `(`, or `[expr]` is a statement, not a declaration.
        """
        k = self.current.kind
        if k in _TYPE_TOKENS or k is TokenKind.KW_VAR:
            return True
        if k is TokenKind.IDENT:
            if self.peek(1).kind is TokenKind.IDENT:
                return True
            if self.peek(1).kind is TokenKind.LBRACKET and self.peek(2).kind is TokenKind.RBRACKET:
                return True
            if self.peek(1).kind is TokenKind.LT:
                return self._generic_decl_ahead()
        return False

    def _generic_decl_ahead(self) -> bool:
        """With current=IDENT and peek(1)=`<`, scan a balanced `<...>`; it's a
        declaration if an IDENT follows the matching `>`. Bails at
        `;`/`{`/`}`/EOF so a comparison like `a < b;` stays a statement."""
        depth = 0
        i = 1
        while True:
            kind = self.peek(i).kind
            if kind is TokenKind.LT:
                depth += 1
            elif kind is TokenKind.GT:
                depth -= 1
                if depth == 0:
                    return self.peek(i + 1).kind is TokenKind.IDENT
            elif kind in (TokenKind.EOF, TokenKind.SEMICOLON, TokenKind.LBRACE, TokenKind.RBRACE):
                return False
            i += 1

    def parse(self) -> list:
        items: list = []
        while self.current.kind is not TokenKind.EOF:
            if self.current.kind is TokenKind.KW_IMPORT:
                items.append(self.import_decl())
            elif self.current.kind is TokenKind.KW_INTERFACE:
                items.append(self.interface_decl())
            elif self.current.kind in (TokenKind.KW_CLASS, TokenKind.KW_ABSTRACT):
                items.append(self.class_decl())
            elif self._is_decl_start():
                if self.current.kind is TokenKind.KW_VAR:
                    items.append(self.var_decl())
                else:
                    t = self.type_name()
                    name = self.expect(TokenKind.IDENT).text
                    if self.current.kind is TokenKind.LPAREN:
                        items.append(self._finish_func(t, name))
                    else:
                        items.append(self._finish_var(t, name))
            else:
                items.append(self.statement())
        return items

    def _finish_func(self, ret_type: str, name: str) -> FuncDecl:
        params = self.param_list()
        body = self.block()
        return FuncDecl(ret_type, name, params, body)

    def _finish_var(self, var_type: str, name: str) -> Stmt:
        if self.current.kind is TokenKind.ASSIGN:
            self.advance()
            init = self.expr()
        else:
            init = None
        self.expect(TokenKind.SEMICOLON)
        return VarDecl(var_type, name, init)


    def import_decl(self) -> Import:
        self.expect(TokenKind.KW_IMPORT)
        if self.current.kind is not TokenKind.STRING:
            raise ParseError(
                f"import wants a \"path\" string, got {self.current.kind.name} "
                f"at position {self.current.pos}"
            )
        path = self.advance().text
        self.expect(TokenKind.SEMICOLON)
        return Import(path)

    def class_decl(self) -> ClassDecl:
        is_abstract = False
        if self.current.kind is TokenKind.KW_ABSTRACT:
            self.advance()
            is_abstract = True
        self.expect(TokenKind.KW_CLASS)
        name = self.expect(TokenKind.IDENT).text

        type_params: list[str] = []
        if self.current.kind is TokenKind.LT:
            self.advance()
            type_params.append(self.expect(TokenKind.IDENT).text)
            while self.current.kind is TokenKind.COMMA:
                self.advance()
                type_params.append(self.expect(TokenKind.IDENT).text)
            self.expect(TokenKind.GT)

        bases: list[str] = []
        if self.current.kind is TokenKind.COLON:
            self.advance()
            bases.append(self.expect(TokenKind.IDENT).text)
            while self.current.kind is TokenKind.COMMA:
                self.advance()
                bases.append(self.expect(TokenKind.IDENT).text)

        self.expect(TokenKind.LBRACE)

        fields: list[FieldDecl] = []
        methods: list[MethodDecl] = []
        ctor: CtorDecl | None = None

        while self.current.kind is not TokenKind.RBRACE:
            if self.current.kind is TokenKind.EOF:
                raise ParseError(f"unexpected end of input: missing '}}' for class {name!r}")
            visibility = None
            if self.current.kind in _VISIBILITY:
                visibility = _VISIBILITY[self.advance().kind]
            if self.current.kind is TokenKind.KW_ABSTRACT:
                self.advance()
                ret_type = self.type_name()
                mname = self.expect(TokenKind.IDENT).text
                params = self.param_list()
                self.expect(TokenKind.SEMICOLON)
                methods.append(MethodDecl(
                    ret_type, mname, params, [], is_abstract=True,
                    visibility=visibility or "private",
                ))
            elif self.current.kind is TokenKind.IDENT and self.current.text == name \
                    and self.peek(1).kind is TokenKind.LPAREN:
                if ctor is not None:
                    raise ParseError(f"class {name!r} has more than one constructor")
                ctor = self.ctor_decl(visibility or "public")
            else:
                member_type = self.type_name()
                member_name = self.expect(TokenKind.IDENT).text
                if self.current.kind is TokenKind.LPAREN:
                    methods.append(self.method_decl(member_type, member_name, visibility or "private"))
                else:
                    self.expect(TokenKind.SEMICOLON)
                    fields.append(FieldDecl(member_type, member_name, visibility or "private"))

        self.expect(TokenKind.RBRACE)
        return ClassDecl(
            name, fields, methods, ctor,
            bases=bases, is_abstract=is_abstract, type_params=type_params,
        )

    def interface_decl(self) -> InterfaceDecl:
        self.expect(TokenKind.KW_INTERFACE)
        name = self.expect(TokenKind.IDENT).text
        self.expect(TokenKind.LBRACE)
        methods: list[MethodSig] = []
        while self.current.kind is not TokenKind.RBRACE:
            if self.current.kind is TokenKind.EOF:
                raise ParseError(f"unexpected end of input: missing '}}' for interface {name!r}")
            ret_type = self.type_name()
            mname = self.expect(TokenKind.IDENT).text
            params = self.param_list()
            self.expect(TokenKind.SEMICOLON)
            methods.append(MethodSig(ret_type, mname, params))
        self.expect(TokenKind.RBRACE)
        return InterfaceDecl(name, methods)

    def ctor_decl(self, visibility: str) -> CtorDecl:
        self.advance()
        params = self.param_list()
        body = self.block()
        return CtorDecl(params, body, visibility)

    def method_decl(self, ret_type: str, name: str, visibility: str) -> MethodDecl:
        params = self.param_list()
        body = self.block()
        return MethodDecl(ret_type, name, params, body, visibility=visibility)

    def param_list(self) -> list[Param]:
        self.expect(TokenKind.LPAREN)
        params: list[Param] = []
        if self.current.kind is not TokenKind.RPAREN:
            params.append(self.param())
            while self.current.kind is TokenKind.COMMA:
                self.advance()
                params.append(self.param())
        self.expect(TokenKind.RPAREN)
        return params

    def param(self) -> Param:
        var_type = self.type_name()
        name = self.expect(TokenKind.IDENT).text
        return Param(var_type, name)

    def statement(self) -> Stmt:
        if self._is_decl_start():
            return self.var_decl()
        match self.current.kind:
            case TokenKind.KW_PRINT:
                return self.print_stmt()
            case TokenKind.KW_IF:
                return self.if_stmt()
            case TokenKind.KW_WHILE:
                return self.while_stmt()
            case TokenKind.KW_FOR:
                return self.for_stmt()
            case TokenKind.KW_RETURN:
                return self.return_stmt()
            case TokenKind.KW_SUPER:
                return self.super_stmt()
            case TokenKind.IDENT | TokenKind.KW_THIS:
                return self.assign_or_expr_stmt()
        raise ParseError(
            f"expected a statement, got {self.current.kind.name} "
            f"at position {self.current.pos}"
        )

    def block(self) -> list[Stmt]:
        self.expect(TokenKind.LBRACE)
        stmts: list[Stmt] = []
        while self.current.kind is not TokenKind.RBRACE:
            if self.current.kind is TokenKind.EOF:
                raise ParseError("unexpected end of input: missing '}'")
            stmts.append(self.statement())
        self.expect(TokenKind.RBRACE)
        return stmts

    def var_decl(self) -> Stmt:
        if self.current.kind is TokenKind.KW_VAR:
            self.advance()
            name = self.expect(TokenKind.IDENT).text
            return self._finish_var("var", name)
        var_type = self.type_name()
        name = self.expect(TokenKind.IDENT).text
        return self._finish_var(var_type, name)

    def assign_or_expr_stmt(self) -> Stmt:
        expr = self.expr()
        if self.current.kind is TokenKind.ASSIGN:
            self.advance()
            value = self.expr()
            self.expect(TokenKind.SEMICOLON)
            if not isinstance(expr, (Identifier, FieldAccess, Index)):
                raise ParseError("invalid assignment target")
            return Assign(expr, value)
        self.expect(TokenKind.SEMICOLON)
        return ExprStmt(expr)

    def print_stmt(self) -> Stmt:
        self.expect(TokenKind.KW_PRINT)
        self.expect(TokenKind.LPAREN)
        expr = self.expr()
        self.expect(TokenKind.RPAREN)
        self.expect(TokenKind.SEMICOLON)
        return PrintStmt(expr)

    def if_stmt(self) -> Stmt:
        self.expect(TokenKind.KW_IF)
        self.expect(TokenKind.LPAREN)
        cond = self.expr()
        self.expect(TokenKind.RPAREN)
        then_body = self.block()

        else_body: list[Stmt] | None = None
        if self.current.kind is TokenKind.KW_ELSE:
            self.advance()
            if self.current.kind is TokenKind.KW_IF:
                else_body = [self.if_stmt()]
            else:
                else_body = self.block()
        return If(cond, then_body, else_body)

    def while_stmt(self) -> Stmt:
        self.expect(TokenKind.KW_WHILE)
        self.expect(TokenKind.LPAREN)
        cond = self.expr()
        self.expect(TokenKind.RPAREN)
        body = self.block()
        return While(cond, body)

    def for_stmt(self) -> Stmt:
        self.expect(TokenKind.KW_FOR)
        self.expect(TokenKind.LPAREN)

        if self.current.kind is TokenKind.SEMICOLON:
            init = None
            self.advance()
        elif self._is_decl_start():
            init = self.var_decl()          # consumes its own ';'
        else:
            init = self.assign_or_expr_stmt()  # consumes its own ';'

        cond = None if self.current.kind is TokenKind.SEMICOLON else self.expr()
        self.expect(TokenKind.SEMICOLON)

        step = None if self.current.kind is TokenKind.RPAREN else self._simple_step()
        self.expect(TokenKind.RPAREN)

        body = self.block()
        return For(init, cond, step, body)

    def _simple_step(self) -> Stmt:
        """The third clause of a for-loop: an assignment or expression, but with
        no trailing ';' (the ')' ends it)."""
        expr = self.expr()
        if self.current.kind is TokenKind.ASSIGN:
            self.advance()
            value = self.expr()
            if not isinstance(expr, (Identifier, FieldAccess, Index)):
                raise ParseError("invalid assignment target in for-loop step")
            return Assign(expr, value)
        return ExprStmt(expr)

    def return_stmt(self) -> Stmt:
        self.expect(TokenKind.KW_RETURN)
        value = None if self.current.kind is TokenKind.SEMICOLON else self.expr()
        self.expect(TokenKind.SEMICOLON)
        return Return(value)

    def super_stmt(self) -> Stmt:
        self.expect(TokenKind.KW_SUPER)
        args = self.arg_list()
        self.expect(TokenKind.SEMICOLON)
        return SuperCall(args)

    def expr(self) -> Expr:
        return self.logic_or()

    def logic_or(self) -> Expr:
        node = self.logic_and()
        while self.current.kind is TokenKind.OR:
            self.advance()
            node = BinaryOp("||", node, self.logic_and())
        return node

    def logic_and(self) -> Expr:
        node = self.comparison()
        while self.current.kind is TokenKind.AND:
            self.advance()
            node = BinaryOp("&&", node, self.comparison())
        return node

    def comparison(self) -> Expr:
        node = self.additive()
        if self.current.kind in _COMPARISON_OPS:
            op = self.advance().text
            node = BinaryOp(op, node, self.additive())
        return node

    def additive(self) -> Expr:
        node = self.term()
        while self.current.kind in (TokenKind.PLUS, TokenKind.MINUS):
            op = self.advance().text
            node = BinaryOp(op, node, self.term())
        return node

    def term(self) -> Expr:
        node = self.factor()
        while self.current.kind in (TokenKind.STAR, TokenKind.SLASH):
            op = self.advance().text
            node = BinaryOp(op, node, self.factor())
        return node

    def factor(self) -> Expr:
        if self.current.kind is TokenKind.MINUS:
            self.advance()
            return UnaryOp("-", self.factor())
        if self.current.kind is TokenKind.NOT:
            self.advance()
            return UnaryOp("!", self.factor())
        return self.postfix()

    def postfix(self) -> Expr:
        node = self.primary()
        while self.current.kind in (TokenKind.DOT, TokenKind.LBRACKET):
            if self.current.kind is TokenKind.DOT:
                self.advance()
                name = self.expect(TokenKind.IDENT).text
                if self.current.kind is TokenKind.LPAREN:
                    node = MethodCall(node, name, self.arg_list())
                else:
                    node = FieldAccess(node, name)
            else:
                self.advance()
                index = self.expr()
                self.expect(TokenKind.RBRACKET)
                node = Index(node, index)
        return node

    def primary(self) -> Expr:
        tok = self.current

        if tok.kind is TokenKind.INT:
            self.advance()
            return IntLiteral(int(tok.text))

        if tok.kind is TokenKind.FLOAT:
            self.advance()
            return FloatLiteral(float(tok.text))

        if tok.kind is TokenKind.STRING:
            self.advance()
            return StringLiteral(tok.text)

        if tok.kind is TokenKind.KW_TRUE:
            self.advance()
            return BoolLiteral(True)

        if tok.kind is TokenKind.KW_FALSE:
            self.advance()
            return BoolLiteral(False)

        if tok.kind is TokenKind.KW_NULL:
            self.advance()
            return NullLiteral()

        if tok.kind is TokenKind.KW_THIS:
            self.advance()
            return ThisExpr()

        if tok.kind is TokenKind.KW_NEW:
            self.advance()
            base = self.type_name_base()
            if self.current.kind is TokenKind.LT:
                self.advance()
                args = [self.type_name()]
                while self.current.kind is TokenKind.COMMA:
                    self.advance()
                    args.append(self.type_name())
                self.expect(TokenKind.GT)
                base += "<" + ",".join(args) + ">"
            if self.current.kind is TokenKind.LBRACKET:
                self.advance()
                size = self.expr()
                self.expect(TokenKind.RBRACKET)
                return NewArray(base, size)
            return New(base, self.arg_list())


        if tok.kind is TokenKind.IDENT:
            self.advance()
            if self.current.kind is TokenKind.LPAREN:
                return Call(tok.text, self.arg_list())
            return Identifier(tok.text)

        if tok.kind is TokenKind.LPAREN:
            self.advance()
            node = self.expr()
            self.expect(TokenKind.RPAREN)
            return node

        raise ParseError(f"unexpected {tok.kind.name} at position {tok.pos}")

    def arg_list(self) -> list[Expr]:
        self.expect(TokenKind.LPAREN)
        args: list[Expr] = []
        if self.current.kind is not TokenKind.RPAREN:
            args.append(self.expr())
            while self.current.kind is TokenKind.COMMA:
                self.advance()
                args.append(self.expr())
        self.expect(TokenKind.RPAREN)
        return args


def parse(tokens: list[Token]) -> list:
    return Parser(tokens).parse()
