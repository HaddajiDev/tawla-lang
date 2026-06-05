"""Monomorphization: stamp out a real class for every generic instantiation,
before sema ever runs.

Write `class Box<T> { T value; ... }` and use it as `Box<int>`, and this pass
builds a concrete `Box$int` (with `T` swapped for `int`) and rewrites every
`Box<int>` reference to point at it. By the time the rest of the compiler runs,
there are no type parameters left — just plain classes.

Heads up (first cut): only generic *classes* for now (no generic functions or
methods), and the type arguments have to be concrete — no nesting like
`Box<Box<int>>` yet.
"""

from dataclasses import replace

from .ast_nodes import (
    Assign,
    BinaryOp,
    Call,
    ClassDecl,
    CtorDecl,
    ExprStmt,
    FieldAccess,
    For,
    FuncDecl,
    If,
    Index,
    InterfaceDecl,
    MethodCall,
    MethodDecl,
    New,
    NewArray,
    Param,
    PrintStmt,
    Return,
    SuperCall,
    Ternary,
    Throw,
    TryCatch,
    UnaryOp,
    VarDecl,
    While,
)
from .sema import SemaError


def _mangle(typestr: str) -> str:
    """A concrete name for a generic instantiation: Box<int> -> Box$int."""
    return (
        typestr.replace("[]", "_arr")
        .replace("<", "$")
        .replace(">", "")
        .replace(",", "$")
        .replace(" ", "")
    )


def _split_args(inner: str) -> list[str]:
    """Split type-argument list at top-level commas (respecting nested <>)."""
    args, depth, cur = [], 0, ""
    for ch in inner:
        if ch == "<":
            depth += 1
            cur += ch
        elif ch == ">":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            args.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        args.append(cur)
    return args


class _Mono:
    def __init__(self, generics: dict[str, ClassDecl]):
        self.generics = generics
        self.queue: list[tuple[str, tuple[str, ...]]] = []
        self.seen: set[tuple[str, ...]] = set()

    def _enqueue(self, base: str, args: list[str]) -> None:
        key = (base, tuple(args))
        if key not in self.seen:
            self.seen.add(key)
            self.queue.append(key)


    def xf_type(self, t: str, subst: dict[str, str]) -> str:
        suffix = ""
        while t.endswith("[]"):
            t, suffix = t[:-2], suffix + "[]"

        if "<" in t:
            base = t[: t.index("<")]
            args = [self.xf_type(a, subst) for a in _split_args(t[t.index("<") + 1 : -1])]
            if base not in self.generics:
                raise SemaError(f"{base!r} is not a generic class")
            if len(args) != len(self.generics[base].type_params):
                raise SemaError(
                    f"generic class {base!r} expects "
                    f"{len(self.generics[base].type_params)} type argument(s)"
                )
            self._enqueue(base, args)
            return _mangle(f"{base}<{','.join(args)}>") + suffix

        return subst.get(t, t) + suffix


    def xf_decl(self, decl, subst: dict[str, str], rename: str | None = None):
        if isinstance(decl, ClassDecl):
            return replace(
                decl,
                name=rename or decl.name,
                type_params=[] if rename else decl.type_params,
                bases=[self.xf_type(b, subst) for b in decl.bases],
                fields=[replace(f, var_type=self.xf_type(f.var_type, subst)) for f in decl.fields],
                methods=[self.xf_method(m, subst) for m in decl.methods],
                ctor=None if decl.ctor is None else self.xf_ctor(decl.ctor, subst),
            )
        if isinstance(decl, InterfaceDecl):
            return replace(decl, methods=[self.xf_sig(m, subst) for m in decl.methods])
        if isinstance(decl, FuncDecl):
            return replace(
                decl,
                ret_type=self.xf_type(decl.ret_type, subst),
                params=[self.xf_param(p, subst) for p in decl.params],
                body=[self.xf_stmt(s, subst) for s in decl.body],
            )
        return self.xf_stmt(decl, subst)

    def xf_method(self, m: MethodDecl, subst):
        return replace(
            m,
            ret_type=self.xf_type(m.ret_type, subst),
            params=[self.xf_param(p, subst) for p in m.params],
            body=[self.xf_stmt(s, subst) for s in m.body],
        )

    def xf_ctor(self, c: CtorDecl, subst):
        return replace(
            c,
            params=[self.xf_param(p, subst) for p in c.params],
            body=[self.xf_stmt(s, subst) for s in c.body],
        )

    def xf_sig(self, m, subst):
        return replace(
            m,
            ret_type=self.xf_type(m.ret_type, subst),
            params=[self.xf_param(p, subst) for p in m.params],
        )

    def xf_param(self, p: Param, subst):
        return replace(p, var_type=self.xf_type(p.var_type, subst))

    def xf_stmt(self, s, subst):
        if isinstance(s, VarDecl):
            vt = s.var_type if s.var_type == "var" else self.xf_type(s.var_type, subst)
            init = None if s.init is None else self.xf_expr(s.init, subst)
            return replace(s, var_type=vt, init=init)
        if isinstance(s, Assign):
            return replace(s, target=self.xf_expr(s.target, subst), value=self.xf_expr(s.value, subst))
        if isinstance(s, (ExprStmt, PrintStmt)):
            return replace(s, expr=self.xf_expr(s.expr, subst))
        if isinstance(s, If):
            return replace(
                s,
                cond=self.xf_expr(s.cond, subst),
                then_body=[self.xf_stmt(x, subst) for x in s.then_body],
                else_body=None if s.else_body is None else [self.xf_stmt(x, subst) for x in s.else_body],
            )
        if isinstance(s, While):
            return replace(s, cond=self.xf_expr(s.cond, subst), body=[self.xf_stmt(x, subst) for x in s.body])
        if isinstance(s, For):
            return replace(
                s,
                init=None if s.init is None else self.xf_stmt(s.init, subst),
                cond=None if s.cond is None else self.xf_expr(s.cond, subst),
                step=None if s.step is None else self.xf_stmt(s.step, subst),
                body=[self.xf_stmt(x, subst) for x in s.body],
            )
        if isinstance(s, Return):
            return replace(s, value=None if s.value is None else self.xf_expr(s.value, subst))
        if isinstance(s, SuperCall):
            return replace(s, args=[self.xf_expr(a, subst) for a in s.args])
        if isinstance(s, Throw):
            return replace(s, value=self.xf_expr(s.value, subst))
        if isinstance(s, TryCatch):
            return replace(
                s,
                try_body=[self.xf_stmt(x, subst) for x in s.try_body],
                catch_body=[self.xf_stmt(x, subst) for x in s.catch_body],
            )
        return s

    def xf_expr(self, e, subst):
        if isinstance(e, New):
            return replace(e, class_name=self.xf_type(e.class_name, subst),
                           args=[self.xf_expr(a, subst) for a in e.args])
        if isinstance(e, NewArray):
            return replace(e, elem_type=self.xf_type(e.elem_type, subst), size=self.xf_expr(e.size, subst))
        if isinstance(e, Index):
            return replace(e, arr=self.xf_expr(e.arr, subst), index=self.xf_expr(e.index, subst))
        if isinstance(e, FieldAccess):
            return replace(e, obj=self.xf_expr(e.obj, subst))
        if isinstance(e, MethodCall):
            return replace(e, obj=self.xf_expr(e.obj, subst), args=[self.xf_expr(a, subst) for a in e.args])
        if isinstance(e, Call):
            return replace(e, args=[self.xf_expr(a, subst) for a in e.args])
        if isinstance(e, UnaryOp):
            return replace(e, operand=self.xf_expr(e.operand, subst))
        if isinstance(e, BinaryOp):
            return replace(e, left=self.xf_expr(e.left, subst), right=self.xf_expr(e.right, subst))
        if isinstance(e, Ternary):
            return replace(
                e,
                cond=self.xf_expr(e.cond, subst),
                then_expr=self.xf_expr(e.then_expr, subst),
                else_expr=self.xf_expr(e.else_expr, subst),
            )
        return e


def monomorphize(items: list) -> list:
    generics = {c.name: c for c in items if isinstance(c, ClassDecl) and c.type_params}
    if not generics:
        return items

    mono = _Mono(generics)
    result = [
        mono.xf_decl(it, {})
        for it in items
        if not (isinstance(it, ClassDecl) and it.type_params)
    ]

    i = 0
    while i < len(mono.queue):
        base, args = mono.queue[i]
        i += 1
        gdecl = generics[base]
        subst = dict(zip(gdecl.type_params, args))
        name = _mangle(f"{base}<{','.join(args)}>")
        result.append(mono.xf_decl(gdecl, subst, rename=name))

    return result
