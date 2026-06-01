"""The AST node types — the little tree the parser builds and codegen walks over."""

from dataclasses import dataclass, field


class Expr:
    """Parent of everything that's an expression (i.e. produces a value)."""


class Stmt:
    """Parent of everything that's a statement (i.e. does something)."""


@dataclass
class IntLiteral(Expr):
    value: int


@dataclass
class FloatLiteral(Expr):
    value: float


@dataclass
class NullLiteral(Expr):
    pass


@dataclass
class BoolLiteral(Expr):
    value: bool


@dataclass
class StringLiteral(Expr):
    value: str


@dataclass
class Identifier(Expr):
    name: str


@dataclass
class Call(Expr):
    name: str
    args: list[Expr]


@dataclass
class ThisExpr(Expr):
    pass


@dataclass
class New(Expr):
    class_name: str
    args: list[Expr]


@dataclass
class NewArray(Expr):
    elem_type: str
    size: Expr


@dataclass
class Index(Expr):
    arr: Expr
    index: Expr


@dataclass
class FieldAccess(Expr):
    obj: Expr
    field: str


@dataclass
class MethodCall(Expr):
    obj: Expr
    method: str
    args: list[Expr]


@dataclass
class UnaryOp(Expr):
    op: str
    operand: Expr


@dataclass
class BinaryOp(Expr):
    op: str
    left: Expr
    right: Expr




@dataclass
class VarDecl(Stmt):
    var_type: str
    name: str
    init: Expr


@dataclass
class Assign(Stmt):
    target: Expr
    value: Expr


@dataclass
class ExprStmt(Stmt):
    expr: Expr


@dataclass
class PrintStmt(Stmt):
    expr: Expr


@dataclass
class If(Stmt):
    cond: Expr
    then_body: list[Stmt]
    else_body: list[Stmt] | None


@dataclass
class While(Stmt):
    cond: Expr
    body: list[Stmt]


@dataclass
class For(Stmt):
    init: Stmt | None
    cond: Expr | None
    step: Stmt | None
    body: list[Stmt]


@dataclass
class Return(Stmt):
    value: Expr | None


@dataclass
class SuperCall(Stmt):
    args: list[Expr]




@dataclass
class Param:
    var_type: str
    name: str


@dataclass
class FuncDecl:
    ret_type: str
    name: str
    params: list[Param]
    body: list[Stmt]




@dataclass
class FieldDecl:
    var_type: str
    name: str


@dataclass
class MethodDecl:
    ret_type: str
    name: str
    params: list[Param]
    body: list[Stmt]
    is_abstract: bool = False


@dataclass
class MethodSig:
    ret_type: str
    name: str
    params: list[Param]


@dataclass
class CtorDecl:
    params: list[Param]
    body: list[Stmt]


@dataclass
class ClassDecl:
    name: str
    fields: list[FieldDecl]
    methods: list[MethodDecl]
    ctor: CtorDecl | None
    bases: list[str] = field(default_factory=list)
    is_abstract: bool = False
    type_params: list[str] = field(default_factory=list)
    parent: str | None = None
    interfaces: list[str] = field(default_factory=list)


@dataclass
class InterfaceDecl:
    name: str
    methods: list[MethodSig]


@dataclass
class Import:
    """A top-level `import "other.twl";` — pulls another file's declarations in.

    `path` is whatever string the program wrote, resolved relative to the file
    doing the importing. The loader expands these away before anything else runs,
    so the rest of the pipeline never sees an Import node.
    """

    path: str
