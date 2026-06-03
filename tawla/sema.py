"""Semantic analysis: the type-checker. Sits between the parser and codegen.

It walks the tree, gives every expression a type (int, bool, string, a class, an
array...), and shoots down anything that doesn't add up with a SemaError —
`int x = true;`, calling a method that isn't there, that kind of thing. It also
works out `var` types and checks that classes actually implement what they claim
to. If this pass is happy, codegen can stop worrying and just trust the tree.
"""

from .ast_nodes import (
    Assign,
    BinaryOp,
    BoolLiteral,
    Call,
    ClassDecl,
    Expr,
    ExprStmt,
    FieldAccess,
    FloatLiteral,
    For,
    FuncDecl,
    Identifier,
    If,
    Index,
    InterfaceDecl,
    IntLiteral,
    MethodCall,
    New,
    NewArray,
    NullLiteral,
    PrintStmt,
    Return,
    Stmt,
    StringLiteral,
    SuperCall,
    Ternary,
    ThisExpr,
    UnaryOp,
    VarDecl,
    While,
)


class Type:
    """A Tawla type, identified by name: 'int', 'bool', or a class name."""

    def __init__(self, name: str):
        self.name = name

    def __eq__(self, other) -> bool:
        return isinstance(other, Type) and self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)

    def __repr__(self) -> str:
        return self.name


INT = Type("int")
FLOAT = Type("float")
BOOL = Type("bool")
STRING = Type("string")
VOID = Type("void")
NULL = Type("null")

_NUMERIC = {INT, FLOAT}


class ClassInfo:
    def __init__(self, name: str):
        self.name = name
        self.parent: str | None = None
        self.interfaces: set[str] = set()
        self.fields: dict[str, Type] = {}
        self.methods: dict[str, tuple[list[Type], Type]] = {}
        self.field_vis: dict[str, tuple[str, str]] = {}   # name -> (visibility, owner class)
        self.method_vis: dict[str, tuple[str, str]] = {}
        self.ctor_vis: str = "public"
        self.ctor: list[Type] | None = None
        self.is_abstract: bool = False
        self.abstract_methods: set[str] = set()


class InterfaceInfo:
    def __init__(self, name: str):
        self.name = name
        self.methods: dict[str, tuple[list[Type], Type]] = {}


class SemaError(Exception):
    pass


_ARITHMETIC = {"+", "-", "*", "/"}
_ORDERING = {"<", "<=", ">", ">="}
_EQUALITY = {"==", "!="}
_LOGICAL = {"&&", "||"}

# Builtins with a fixed, non-numeric signature: (param types, return type).
# The __io_* ones are the native primitives behind stdlib/IO.twl.
_BUILTINS = {
    "collect": ([], VOID),
    "__live": ([], INT),
    "__io_read_int": ([], INT),
    "__io_read_float": ([], FLOAT),
    "__io_read_line": ([], STRING),
    "__io_write": ([STRING], VOID),
    "panic": ([STRING], VOID),
    "__http_listen": ([INT], INT),
    "__http_port": ([INT], INT),
    "__http_accept": ([INT], INT),
    "__http_method": ([INT], STRING),
    "__http_path": ([INT], STRING),
    "__http_body": ([INT], STRING),
    "__http_respond": ([INT, INT, STRING], VOID),
    "charAt": ([STRING, INT], INT),
    "substring": ([STRING, INT, INT], STRING),
    "toInt": ([STRING], INT),
    "toFloat": ([STRING], FLOAT),
}

# Math builtins, keyed by name -> number of arguments. Their argument and return
# types follow the numeric rules (int or float, ints widen), so they're checked
# specially rather than with a fixed signature.
_MATH_FLOAT = {"sqrt": 1, "pow": 2, "floor": 1, "ceil": 1}   # always return float
_MATH_SAME = {"abs": 1}                                       # return matches the arg
_MATH_WIDEST = {"min": 2, "max": 2}                           # float if any arg is float


class Sema:
    def __init__(self):
        self.classes: dict[str, ClassInfo] = {}
        self.interfaces: dict[str, InterfaceInfo] = {}
        self.class_decls: dict[str, ClassDecl] = {}
        self.functions: dict[str, tuple[list[Type], Type]] = {}
        self.scope: dict[str, Type] = {}
        self.current_ret: Type | None = None
        self.current_class: str | None = None
        self.in_ctor: bool = False
        self._resolving: set[str] = set()
        self._done_resolving: set[str] = set()

    def check(self, items: list) -> list:
        interfaces = [it for it in items if isinstance(it, InterfaceDecl)]
        classes = [it for it in items if isinstance(it, ClassDecl)]
        funcs = [it for it in items if isinstance(it, FuncDecl)]
        main_body = [
            it for it in items
            if not isinstance(it, (ClassDecl, FuncDecl, InterfaceDecl))
        ]

        names = set()
        for decl in (*interfaces, *classes):
            if decl.name in names:
                raise SemaError(f"type {decl.name!r} already declared")
            names.add(decl.name)
        for i in interfaces:
            self.interfaces[i.name] = InterfaceInfo(i.name)
        for c in classes:
            self.class_decls[c.name] = c
            self.classes[c.name] = ClassInfo(c.name)

        for i in interfaces:
            self._fill_interface(i)
        for c in classes:
            self._classify_bases(c)
        for c in classes:
            self._resolve_class(c.name)
        for c in classes:
            self._verify_implements(c)
        for f in funcs:
            self._declare_func(f)

        for c in classes:
            self._check_class_bodies(c)
        for f in funcs:
            self._check_function(f)

        self.scope, self.current_ret, self.current_class = {}, INT, None
        for stmt in main_body:
            self._check_stmt(stmt)
        return items

    def _type_from_name(self, name: str) -> Type:
        if name == "int":
            return INT
        if name in ("float", "double"):
            return FLOAT
        if name == "bool":
            return BOOL
        if name == "string":
            return STRING
        if name.endswith("[]"):
            self._type_from_name(name[:-2])
            return Type(name)
        if name in self.classes or name in self.interfaces:
            return Type(name)
        if name == "void":
            raise SemaError("'void' is only valid as a return type")
        raise SemaError(f"unknown type {name!r}")

    def _return_type(self, name: str) -> Type:
        """Like _type_from_name, but `void` is allowed (no return value)."""
        return VOID if name == "void" else self._type_from_name(name)

    def _fill_interface(self, i: InterfaceDecl) -> None:
        info = self.interfaces[i.name]
        for m in i.methods:
            if m.name in info.methods:
                raise SemaError(f"duplicate method {m.name!r} in interface {i.name!r}")
            info.methods[m.name] = (
                [self._type_from_name(p.var_type) for p in m.params],
                self._return_type(m.ret_type),
            )

    def _classify_bases(self, c: ClassDecl) -> None:
        """Split `class C : A, IFoo` into one parent class + several interfaces."""
        for base in c.bases:
            if base in self.interfaces:
                c.interfaces.append(base)
            elif base in self.classes:
                if c.parent is not None:
                    raise SemaError(f"class {c.name!r} cannot extend more than one class")
                c.parent = base
            else:
                raise SemaError(f"class {c.name!r} extends unknown type {base!r}")

    def _verify_implements(self, c: ClassDecl) -> None:
        info = self.classes[c.name]
        for iface in info.interfaces:
            for mname, sig in self.interfaces[iface].methods.items():
                have = info.methods.get(mname)
                if have is None:
                    raise SemaError(
                        f"class {c.name!r} does not implement method {mname!r} "
                        f"required by interface {iface!r}"
                    )
                if have != sig:
                    raise SemaError(
                        f"method {mname!r} in class {c.name!r} does not match "
                        f"interface {iface!r}"
                    )
                if info.method_vis[mname][0] != "public":
                    raise SemaError(
                        f"method {mname!r} implements interface {iface!r} and must be public"
                    )

    def _same_or_subclass(self, cls: str | None, owner: str) -> bool:
        name = cls
        while name is not None:
            if name == owner:
                return True
            name = self.classes[name].parent if name in self.classes else None
        return False

    def _check_access(self, visibility: str, owner: str, what: str) -> None:
        if visibility == "public":
            return
        if visibility == "private":
            if self.current_class != owner:
                raise SemaError(f"{what} is private to class {owner!r}")
        elif visibility == "protected":
            if not self._same_or_subclass(self.current_class, owner):
                raise SemaError(
                    f"{what} is protected; only {owner!r} and its subclasses may use it"
                )

    def _is_reference(self, t: Type) -> bool:
        """True for types that can hold null: string, arrays, classes, interfaces."""
        if t == STRING:
            return True
        if t.name.endswith("[]"):
            return True
        return t.name in self.classes or t.name in self.interfaces

    def _is_subtype(self, sub: Type, sup: Type) -> bool:
        """True if `sub` fits where `sup` is expected: equal, a subclass, or a
        class implementing the interface `sup`."""
        if sub == sup:
            return True
        if sub == INT and sup == FLOAT:
            return True
        if sub == NULL:
            return self._is_reference(sup)
        if sub.name not in self.classes:
            return False
        info = self.classes[sub.name]
        if sup.name in self.interfaces:
            return sup.name in info.interfaces
        name = sub.name
        while name in self.classes:
            parent = self.classes[name].parent
            if parent is None:
                return False
            if parent == sup.name:
                return True
            name = parent
        return False


    def _resolve_class(self, name: str) -> None:
        """Fill a class's fields/methods/ctor, inheriting from its parent."""
        info = self.classes[name]
        if name in self._done_resolving:
            return
        if name in self._resolving:
            raise SemaError(f"inheritance cycle involving class {name!r}")
        self._resolving.add(name)

        c = self.class_decls[name]
        info.is_abstract = c.is_abstract
        info.interfaces = set(c.interfaces)
        if c.parent is not None:
            self._resolve_class(c.parent)
            base = self.classes[c.parent]
            info.parent = c.parent
            info.interfaces |= base.interfaces
            info.fields.update(base.fields)
            info.methods.update(base.methods)
            info.field_vis.update(base.field_vis)
            info.method_vis.update(base.method_vis)
            info.abstract_methods = set(base.abstract_methods)

        for fld in c.fields:
            if fld.name in info.fields:
                raise SemaError(f"field {fld.name!r} in class {name!r} shadows another")
            info.fields[fld.name] = self._type_from_name(fld.var_type)
            info.field_vis[fld.name] = (fld.visibility, name)
        for m in c.methods:
            sig = ([self._type_from_name(p.var_type) for p in m.params],
                   self._return_type(m.ret_type))
            if m.name in info.methods and info.methods[m.name] != sig:
                raise SemaError(
                    f"method {m.name!r} in class {name!r} does not match the "
                    f"signature it overrides"
                )
            if m.name in info.method_vis and info.method_vis[m.name][0] != m.visibility:
                raise SemaError(
                    f"override of method {m.name!r} in class {name!r} must keep "
                    f"visibility {info.method_vis[m.name][0]!r}"
                )
            info.methods[m.name] = sig
            info.method_vis[m.name] = (m.visibility, name)
            if m.is_abstract:
                if m.visibility == "private":
                    raise SemaError(f"abstract method {m.name!r} cannot be private")
                if not c.is_abstract:
                    raise SemaError(
                        f"abstract method {m.name!r} in non-abstract class {name!r}"
                    )
                info.abstract_methods.add(m.name)
            else:
                info.abstract_methods.discard(m.name)
        if c.ctor is not None:
            info.ctor = [self._type_from_name(p.var_type) for p in c.ctor.params]
            info.ctor_vis = c.ctor.visibility

        if not c.is_abstract and info.abstract_methods:
            missing = ", ".join(sorted(info.abstract_methods))
            raise SemaError(
                f"class {name!r} must implement abstract method(s) {missing} "
                f"(or be declared abstract)"
            )

        self._resolving.discard(name)
        self._done_resolving.add(name)

    def _declare_func(self, func: FuncDecl) -> None:
        if func.name in self.functions:
            raise SemaError(f"function {func.name!r} already declared")
        params = [self._type_from_name(p.var_type) for p in func.params]
        self.functions[func.name] = (params, self._return_type(func.ret_type))

    def _check_function(self, func: FuncDecl) -> None:
        self.current_class = None
        self.current_ret = self._return_type(func.ret_type)
        self.scope = {p.name: self._type_from_name(p.var_type) for p in func.params}
        for stmt in func.body:
            self._check_stmt(stmt)

    def _check_class_bodies(self, c: ClassDecl) -> None:
        info = self.classes[c.name]
        self.in_ctor = False
        for m in c.methods:
            self.current_class = c.name
            self.current_ret = info.methods[m.name][1]
            self.scope = {p.name: self._type_from_name(p.var_type) for p in m.params}
            for stmt in m.body:
                self._check_stmt(stmt)
        if c.ctor is not None:
            self.current_class = c.name
            self.current_ret = None
            self.in_ctor = True
            self.scope = {p.name: self._type_from_name(p.var_type) for p in c.ctor.params}
            for stmt in c.ctor.body:
                self._check_stmt(stmt)
            self.in_ctor = False
        self.current_class = None


    def _check_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, VarDecl):
            if stmt.init is None:
                if stmt.var_type == "var":
                    raise SemaError(
                        f"variable {stmt.name!r} declared with 'var' needs an initializer"
                    )
                declared = self._type_from_name(stmt.var_type)
                if stmt.name in self.scope:
                    raise SemaError(f"variable {stmt.name!r} already declared")
                self.scope[stmt.name] = declared
                return
            init_type = self._check_expr(stmt.init)
            if init_type == VOID:
                raise SemaError(f"cannot assign void to variable {stmt.name!r}")
            if stmt.var_type == "var":
                if init_type == NULL:
                    raise SemaError(
                        f"cannot infer a type for {stmt.name!r} from null; "
                        f"give it an explicit type"
                    )
                declared = init_type
                stmt.var_type = declared.name
            else:
                declared = self._type_from_name(stmt.var_type)
                if not self._is_subtype(init_type, declared):
                    raise SemaError(
                        f"cannot initialize {declared} variable "
                        f"{stmt.name!r} with a {init_type} value"
                    )
            if stmt.name in self.scope:
                raise SemaError(f"variable {stmt.name!r} already declared")
            self.scope[stmt.name] = declared

        elif isinstance(stmt, Assign):
            target_type = self._check_lvalue(stmt.target)
            value_type = self._check_expr(stmt.value)
            if not self._is_subtype(value_type, target_type):
                raise SemaError(
                    f"cannot assign {value_type} to {target_type} target"
                )

        elif isinstance(stmt, SuperCall):
            if not self.in_ctor or self.current_class is None:
                raise SemaError("'super(...)' can only be called from a constructor")
            parent = self.classes[self.current_class].parent
            if parent is None:
                raise SemaError(
                    f"class {self.current_class!r} has no base class to call 'super' on"
                )
            parent_ctor = self.classes[parent].ctor
            if parent_ctor is None:
                if stmt.args:
                    raise SemaError(f"base class {parent!r} constructor takes no arguments")
            else:
                self._check_args(f"{parent} constructor", parent_ctor, stmt.args)

        elif isinstance(stmt, ExprStmt):
            self._check_expr(stmt.expr)

        elif isinstance(stmt, PrintStmt):
            t = self._check_expr(stmt.expr)
            if t not in (INT, FLOAT, BOOL, STRING):
                raise SemaError(f"print expects int, float, bool, or string, got {t}")

        elif isinstance(stmt, If):
            self._require_bool(stmt.cond, "if condition")
            for s in stmt.then_body:
                self._check_stmt(s)
            for s in stmt.else_body or []:
                self._check_stmt(s)

        elif isinstance(stmt, While):
            self._require_bool(stmt.cond, "while condition")
            for s in stmt.body:
                self._check_stmt(s)

        elif isinstance(stmt, For):
            saved = dict(self.scope)   # the loop's own variable is scoped to it
            if stmt.init is not None:
                self._check_stmt(stmt.init)
            if stmt.cond is not None:
                self._require_bool(stmt.cond, "for condition")
            if stmt.step is not None:
                self._check_stmt(stmt.step)
            for s in stmt.body:
                self._check_stmt(s)
            self.scope = saved

        elif isinstance(stmt, Return):
            if stmt.value is None:
                if self.current_ret not in (None, VOID):
                    raise SemaError(f"must return a {self.current_ret} value")
                return
            value_type = self._check_expr(stmt.value)
            if self.current_ret is None:
                raise SemaError("cannot return a value from a constructor")
            if self.current_ret == VOID:
                raise SemaError("cannot return a value from a void method")
            if not self._is_subtype(value_type, self.current_ret):
                raise SemaError(
                    f"cannot return {value_type} from a {self.current_ret} function"
                )

        else:
            raise SemaError(f"cannot type-check statement {type(stmt).__name__}")

    def _check_lvalue(self, target: Expr) -> Type:
        if isinstance(target, Identifier):
            if target.name not in self.scope:
                raise SemaError(f"assignment to undefined variable {target.name!r}")
            return self.scope[target.name]
        if isinstance(target, Index):
            return self._check_expr(target)
        if isinstance(target, FieldAccess):
            obj_type = self._check_expr(target.obj)
            if obj_type == STRING or obj_type.name.endswith("[]"):
                raise SemaError("'.length' is read-only")
            return self._check_expr(target)
        raise SemaError("invalid assignment target")

    def _require_bool(self, expr: Expr, where: str) -> None:
        t = self._check_expr(expr)
        if t != BOOL:
            raise SemaError(f"{where} must be bool, got {t}")


    def _check_expr(self, node: Expr) -> Type:
        if isinstance(node, IntLiteral):
            return INT

        if isinstance(node, FloatLiteral):
            return FLOAT

        if isinstance(node, NullLiteral):
            return NULL

        if isinstance(node, BoolLiteral):
            return BOOL

        if isinstance(node, StringLiteral):
            return STRING

        if isinstance(node, ThisExpr):
            if self.current_class is None:
                raise SemaError("'this' used outside of a method")
            return Type(self.current_class)

        if isinstance(node, Identifier):
            if node.name not in self.scope:
                raise SemaError(f"undefined variable {node.name!r}")
            return self.scope[node.name]

        if isinstance(node, New):
            info = self.classes.get(node.class_name)
            if info is None:
                raise SemaError(f"unknown class {node.class_name!r}")
            if info.is_abstract:
                raise SemaError(f"cannot instantiate abstract class {node.class_name!r}")
            if info.ctor is None:
                if node.args:
                    raise SemaError(
                        f"class {node.class_name!r} has no constructor that takes arguments"
                    )
            else:
                self._check_args(node.class_name, info.ctor, node.args)
            self._check_access(info.ctor_vis, node.class_name,
                               f"constructor of {node.class_name!r}")
            return Type(node.class_name)

        if isinstance(node, NewArray):
            if self._check_expr(node.size) != INT:
                raise SemaError("array size must be int")
            self._type_from_name(node.elem_type)
            return Type(node.elem_type + "[]")

        if isinstance(node, Index):
            arr_type = self._check_expr(node.arr)
            if not arr_type.name.endswith("[]"):
                raise SemaError(f"cannot index a non-array {arr_type}")
            if self._check_expr(node.index) != INT:
                raise SemaError("array index must be int")
            return Type(arr_type.name[:-2])

        if isinstance(node, FieldAccess):
            obj_type = self._check_expr(node.obj)
            if obj_type == STRING:
                if node.field == "length":
                    return INT
                raise SemaError(f"string has no field {node.field!r}")
            if obj_type.name.endswith("[]"):
                if node.field == "length":
                    return INT
                raise SemaError(f"array {obj_type} has no field {node.field!r}")
            info = self.classes.get(obj_type.name)
            if info is None:
                raise SemaError(f"type {obj_type} has no fields")
            if node.field not in info.fields:
                raise SemaError(f"class {obj_type} has no field {node.field!r}")
            vis, owner = info.field_vis[node.field]
            self._check_access(vis, owner, f"field {node.field!r}")
            return info.fields[node.field]

        if isinstance(node, MethodCall):
            obj_type = self._check_expr(node.obj)
            methods = None
            if obj_type.name in self.classes:
                methods = self.classes[obj_type.name].methods
            elif obj_type.name in self.interfaces:
                methods = self.interfaces[obj_type.name].methods
            if methods is None:
                raise SemaError(f"type {obj_type} has no methods")
            if node.method not in methods:
                raise SemaError(f"type {obj_type} has no method {node.method!r}")
            if obj_type.name in self.classes:
                vis, owner = self.classes[obj_type.name].method_vis[node.method]
                self._check_access(vis, owner, f"method {node.method!r}")
            params, ret = methods[node.method]
            self._check_args(node.method, params, node.args)
            return ret

        if isinstance(node, Call):
            if node.name in self.functions:
                params, ret = self.functions[node.name]
                self._check_args(node.name, params, node.args)
                return ret
            ret = self._check_builtin(node.name, node.args)
            if ret is not None:
                return ret
            raise SemaError(f"call to undefined function {node.name!r}")

        if isinstance(node, UnaryOp):
            operand = self._check_expr(node.operand)
            if node.op == "!":
                if operand != BOOL:
                    raise SemaError(f"unary '!' requires bool, got {operand}")
                return BOOL
            if operand not in _NUMERIC:
                raise SemaError(f"unary '-' requires int or float, got {operand}")
            return operand

        if isinstance(node, Ternary):
            if self._check_expr(node.cond) != BOOL:
                raise SemaError("ternary condition must be bool")
            t1 = self._check_expr(node.then_expr)
            t2 = self._check_expr(node.else_expr)
            if t1 == VOID or t2 == VOID:
                raise SemaError("ternary branches cannot be void")
            if self._is_subtype(t2, t1):
                common = t1
            elif self._is_subtype(t1, t2):
                common = t2
            else:
                raise SemaError(
                    f"ternary branches have incompatible types {t1} and {t2}"
                )
            if common == NULL:
                raise SemaError("ternary needs at least one typed branch")
            node.result_type = common.name
            return common

        if isinstance(node, BinaryOp):
            left = self._check_expr(node.left)
            right = self._check_expr(node.right)
            if node.op in _LOGICAL:
                if left != BOOL or right != BOOL:
                    raise SemaError(
                        f"operator {node.op!r} requires bool operands, "
                        f"got {left} and {right}"
                    )
                return BOOL
            if node.op in _ARITHMETIC:
                if node.op == "+" and left == STRING and right == STRING:
                    return STRING
                if left not in _NUMERIC or right not in _NUMERIC:
                    raise SemaError(
                        f"operator {node.op!r} requires numeric operands, "
                        f"got {left} and {right}"
                    )
                return FLOAT if FLOAT in (left, right) else INT
            if node.op in _ORDERING:
                if left not in _NUMERIC or right not in _NUMERIC:
                    raise SemaError(
                        f"operator {node.op!r} requires numeric operands, "
                        f"got {left} and {right}"
                    )
                return BOOL
            if node.op in _EQUALITY:
                if not (self._is_subtype(left, right) or self._is_subtype(right, left)):
                    raise SemaError(
                        f"operator {node.op!r} requires comparable operand types, "
                        f"got {left} and {right}"
                    )
                return BOOL
            raise SemaError(f"unknown operator {node.op!r}")

        raise SemaError(f"cannot type-check expression {type(node).__name__}")

    def _check_builtin(self, name: str, args: list[Expr]) -> Type | None:
        """Type-check a call to a predefined function. Returns its result type, or
        None if `name` isn't a builtin (so the caller can report 'undefined')."""
        if name in _BUILTINS:
            params, ret = _BUILTINS[name]
            self._check_args(name, params, args)
            return ret
        if name in _MATH_FLOAT:
            self._check_numeric(name, args, _MATH_FLOAT[name])
            return FLOAT
        if name in _MATH_SAME:
            return self._check_numeric(name, args, _MATH_SAME[name])[0]
        if name in _MATH_WIDEST:
            types = self._check_numeric(name, args, _MATH_WIDEST[name])
            return FLOAT if FLOAT in types else INT
        if name == "toString":
            self._check_numeric(name, args, 1)
            return STRING
        return None

    def _check_numeric(self, name: str, args: list[Expr], n: int) -> list[Type]:
        if len(args) != n:
            raise SemaError(f"{name!r} expects {n} argument(s), got {len(args)}")
        types = []
        for i, arg in enumerate(args):
            t = self._check_expr(arg)
            if t not in _NUMERIC:
                raise SemaError(
                    f"argument {i + 1} of {name!r} must be int or float, got {t}"
                )
            types.append(t)
        return types

    def _check_args(self, name: str, params: list[Type], args: list[Expr]) -> None:
        if len(args) != len(params):
            raise SemaError(
                f"{name!r} expects {len(params)} argument(s), got {len(args)}"
            )
        for i, (arg, expected) in enumerate(zip(args, params)):
            actual = self._check_expr(arg)
            if not self._is_subtype(actual, expected):
                raise SemaError(
                    f"argument {i + 1} of {name!r} expects {expected}, got {actual}"
                )


def check(items: list) -> list:
    return Sema().check(items)
