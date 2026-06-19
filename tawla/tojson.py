"""Synthesize a `string toJson()` method on every class (unless it defines one).

Runs after monomorphize and before sema, building the method body as ordinary
Tawla AST so the rest of the pipeline handles it with no special cases. Each
field serializes by its static type; string escaping is delegated to the
__json_escape builtin.
"""

from .ast_nodes import (
    Assign,
    BinaryOp,
    Call,
    ClassDecl,
    FieldAccess,
    Identifier,
    If,
    Index,
    IntLiteral,
    MethodCall,
    MethodDecl,
    NullLiteral,
    Return,
    StringLiteral,
    Ternary,
    ThisExpr,
    VarDecl,
    While,
)

_PRIMS = {"int", "float", "bool", "string"}


def synthesize_tojson(items):
    classes = {c.name: c for c in items if isinstance(c, ClassDecl)}
    for c in items:
        if isinstance(c, ClassDecl) and not any(m.name == "toJson" for m in c.methods):
            c.methods.append(_make_tojson(c, classes))
    return items


def _all_fields(c, classes, inherited=False):
    # A class's own toJson can read its own fields (any visibility) plus
    # inherited public/protected fields; inherited *private* fields are not
    # accessible from a subclass, so they're omitted from its JSON.
    fields = []
    for base in c.bases:
        if base in classes:
            fields.extend(_all_fields(classes[base], classes, inherited=True))
    for f in c.fields:
        if inherited and f.visibility == "private":
            continue
        fields.append(f)
    return fields


def _append(stmts, expr):
    stmts.append(Assign(Identifier("__json"), BinaryOp("+", Identifier("__json"), expr)))


def _value_expr(target, type_name, classes):
    """JSON for a scalar field/element `target` of type `type_name`."""
    if type_name in ("int", "float"):
        return Call("toString", [target])
    if type_name == "bool":
        return Ternary(target, StringLiteral("true"), StringLiteral("false"))
    if type_name == "string":
        return Call("__json_escape", [target])
    if type_name in classes:
        return Ternary(
            BinaryOp("==", target, NullLiteral()),
            StringLiteral("null"),
            MethodCall(target, "toJson", []),
        )
    # interface-typed or otherwise non-introspectable field: not serializable
    return StringLiteral("null")


def _make_tojson(c, classes):
    stmts = [VarDecl("string", "__json", StringLiteral("{"))]
    idx = 0
    for n, f in enumerate(_all_fields(c, classes)):
        key = ("," if n > 0 else "") + '"' + f.name + '":'
        _append(stmts, StringLiteral(key))
        field = FieldAccess(ThisExpr(), f.name)
        if f.var_type.endswith("[]"):
            elem_type = f.var_type[:-2]
            ivar = "__i" + str(idx)
            idx += 1
            loop_body = [
                If(
                    BinaryOp(">", Identifier(ivar), IntLiteral(0)),
                    [Assign(Identifier("__json"), BinaryOp("+", Identifier("__json"), StringLiteral(",")))],
                    None,
                ),
                Assign(
                    Identifier("__json"),
                    BinaryOp("+", Identifier("__json"), _value_expr(Index(field, Identifier(ivar)), elem_type, classes)),
                ),
                Assign(Identifier(ivar), BinaryOp("+", Identifier(ivar), IntLiteral(1))),
            ]
            inner = [
                Assign(Identifier("__json"), BinaryOp("+", Identifier("__json"), StringLiteral("["))),
                VarDecl("int", ivar, IntLiteral(0)),
                While(BinaryOp("<", Identifier(ivar), FieldAccess(field, "length")), loop_body),
                Assign(Identifier("__json"), BinaryOp("+", Identifier("__json"), StringLiteral("]"))),
            ]
            stmts.append(
                If(
                    BinaryOp("==", field, NullLiteral()),
                    [Assign(Identifier("__json"), BinaryOp("+", Identifier("__json"), StringLiteral("null")))],
                    inner,
                )
            )
        else:
            _append(stmts, _value_expr(field, f.var_type, classes))
    _append(stmts, StringLiteral("}"))
    stmts.append(Return(Identifier("__json")))
    return MethodDecl("string", "toJson", [], stmts, False, "public")
