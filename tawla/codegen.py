"""Code generation: turn the checked AST into LLVM IR.

Classes become LLVM structs; objects are pointers to heap blocks (allocated
through the GC). Methods are just regular functions with a hidden first argument
`this` and a name like `Class.method` so nothing collides. Free functions and the
loose top-level statements get bundled into `main`. Sema already vetted
everything, so down here we get to assume the tree is sound.
"""

import llvmlite.ir as ir

from .ast_nodes import (
    Assign,
    BinaryOp,
    BoolLiteral,
    Call,
    ClassDecl,
    Expr,
    ExprStmt,
    FieldAccess,
    FuncDecl,
    Identifier,
    If,
    Index,
    InterfaceDecl,
    IntLiteral,
    MethodCall,
    New,
    NewArray,
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

i32 = ir.IntType(32)
i1 = ir.IntType(1)
i8 = ir.IntType(8)
i64 = ir.IntType(64)
i8ptr = i8.as_pointer()
vtable_ptr_ty = i8ptr.as_pointer()

_COMPARISONS = {"<", ">", "<=", ">=", "==", "!="}


class CodeGenError(Exception):
    pass


class CodeGen:
    def __init__(self):
        self.module = ir.Module(name="tawla", context=ir.Context())
        self.functions: dict[str, ir.Function] = {}
        self.struct_types: dict[str, ir.IdentifiedStructType] = {}
        self.field_index: dict[str, dict[str, int]] = {}
        self.class_decls: dict[str, ClassDecl] = {}
        self.parents: dict[str, str | None] = {}
        self._ff_cache: dict[str, list] = {}
        self.vtables: dict[str, ir.GlobalVariable] = {}
        self.vtable_index: dict[str, dict[str, int]] = {}
        self.method_sig: dict[str, dict[str, tuple]] = {}
        self._mt_cache: dict[str, list[str]] = {}

        self.iface_decls: dict[str, InterfaceDecl] = {}
        self.iface_struct: dict[str, ir.IdentifiedStructType] = {}
        self.iface_index: dict[str, dict[str, int]] = {}
        self.iface_sig: dict[str, dict[str, tuple]] = {}
        self.itables: dict[tuple[str, str], ir.GlobalVariable] = {}
        self._ci_cache: dict[str, set[str]] = {}
        self._array_structs: dict[str, ir.LiteralStructType] = {}
        self.symbols: dict[str, ir.AllocaInstr] = {}
        self.builder: ir.IRBuilder | None = None
        self.alloca_builder: ir.IRBuilder | None = None
        self.current_this: ir.Value | None = None
        self._str_counter = 0

        self._declare_runtime()


    def _declare_runtime(self) -> None:
        """Declare the C functions we call and the printf format string."""
        printf_ty = ir.FunctionType(i32, [i8ptr], var_arg=True)
        self.printf = ir.Function(self.module, printf_ty, name="printf")

        self.fflush = ir.Function(self.module, ir.FunctionType(i32, [i8ptr]), name="fflush")
        self.malloc = ir.Function(self.module, ir.FunctionType(i8ptr, [i64]), name="malloc")
        self.memset = ir.Function(
            self.module, ir.FunctionType(i8ptr, [i8ptr, i32, i64]), name="memset"
        )
        self.exit = ir.Function(self.module, ir.FunctionType(ir.VoidType(), [i32]), name="exit")
        self._oob_msg = self._global_string(b"array index out of bounds\n\0", "oob_msg")

        self.strlen = ir.Function(self.module, ir.FunctionType(i64, [i8ptr]), name="strlen")
        self.strcmp = ir.Function(self.module, ir.FunctionType(i32, [i8ptr, i8ptr]), name="strcmp")
        self.strcpy = ir.Function(self.module, ir.FunctionType(i8ptr, [i8ptr, i8ptr]), name="strcpy")
        self.strcat = ir.Function(self.module, ir.FunctionType(i8ptr, [i8ptr, i8ptr]), name="strcat")

        void = ir.VoidType()
        self.gc_alloc = ir.Function(self.module, ir.FunctionType(i8ptr, [i64]), name="gc_alloc")
        self.gc_root_push = ir.Function(self.module, ir.FunctionType(void, [i8ptr, i32]), name="gc_root_push")
        self.gc_root_depth = ir.Function(self.module, ir.FunctionType(i32, []), name="gc_root_depth")
        self.gc_root_settop = ir.Function(self.module, ir.FunctionType(void, [i32]), name="gc_root_settop")
        self.gc_collect = ir.Function(self.module, ir.FunctionType(void, []), name="gc_collect")
        self.gc_live = ir.Function(self.module, ir.FunctionType(i32, []), name="gc_live")

        self._fmt_int = self._global_string(b"%d\n\0", "fmt_int")
        self._fmt_str = self._global_string(b"%s\n\0", "fmt_str")

    def _global_string(self, data: bytes, name: str) -> ir.GlobalVariable:
        """Create an internal constant byte array and return the global."""
        arr = bytearray(data)
        ty = ir.ArrayType(i8, len(arr))
        g = ir.GlobalVariable(self.module, ty, name=name)
        g.linkage = "internal"
        g.global_constant = True
        g.initializer = ir.Constant(ty, arr)
        return g

    def _str_ptr(self, g: ir.GlobalVariable) -> ir.Value:
        """An i8* pointing at the first byte of a global byte-array constant."""
        return self.builder.gep(
            g, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True
        )

    def _array_struct(self, elem_name: str) -> ir.LiteralStructType:
        """The heap layout of an array of `elem_name`: { i32 length, elem[] }."""
        if elem_name not in self._array_structs:
            elem_ty = self._llvm_type(elem_name)
            self._array_structs[elem_name] = ir.LiteralStructType(
                [i32, ir.ArrayType(elem_ty, 0)]
            )
        return self._array_structs[elem_name]

    def _llvm_type(self, name: str) -> ir.Type:
        if name == "int":
            return i32
        if name == "bool":
            return i1
        if name == "string":
            return i8ptr
        if name.endswith("[]"):
            return self._array_struct(name[:-2]).as_pointer()
        struct = self.struct_types.get(name)
        if struct is not None:
            return struct.as_pointer()
        iface = self.iface_struct.get(name)
        if iface is not None:
            return iface
        raise CodeGenError(f"unknown type {name!r}")

    def _ret_llvm(self, name: str) -> ir.Type:
        return ir.VoidType() if name == "void" else self._llvm_type(name)

    @staticmethod
    def _mangle(class_name: str, member: str) -> str:
        return f"{class_name}.{member}"

    @staticmethod
    def _zero(ty: ir.Type) -> ir.Constant:
        return ir.Constant(ty, None if isinstance(ty, ir.PointerType) else 0)


    def generate(self, items: list) -> ir.Module:
        interfaces = [it for it in items if isinstance(it, InterfaceDecl)]
        classes = [it for it in items if isinstance(it, ClassDecl)]
        funcs = [it for it in items if isinstance(it, FuncDecl)]
        main_body = [
            it for it in items
            if not isinstance(it, (ClassDecl, FuncDecl, InterfaceDecl))
        ]

        self._declare_interfaces(interfaces)
        self._declare_class_types(classes)
        self._declare_class_members(classes)
        for func in funcs:
            self._declare_function(func)

        self._build_vtables(classes)
        self._build_itables(classes)
        self._gen_class_members(classes)
        for func in funcs:
            self._gen_callable(self.functions[func.name], func.body, has_this=False)
        self._gen_main(main_body)
        return self.module


    def _declare_interfaces(self, interfaces: list[InterfaceDecl]) -> None:
        ctx = self.module.context
        for i in interfaces:
            self.iface_decls[i.name] = i
            st = ctx.get_identified_type(i.name)
            st.set_body(i8ptr, vtable_ptr_ty)
            self.iface_struct[i.name] = st
        for i in interfaces:
            self.iface_index[i.name] = {m.name: k for k, m in enumerate(i.methods)}
            self.iface_sig[i.name] = {
                m.name: (
                    self._ret_llvm(m.ret_type),
                    [self._llvm_type(p.var_type) for p in m.params],
                )
                for m in i.methods
            }

    def _class_interfaces(self, name: str) -> set[str]:
        """All interfaces a class implements, including via its base class."""
        if name in self._ci_cache:
            return self._ci_cache[name]
        c = self.class_decls[name]
        result = set(c.interfaces)
        if c.parent:
            result |= self._class_interfaces(c.parent)
        self._ci_cache[name] = result
        return result

    def _build_itables(self, classes: list[ClassDecl]) -> None:
        for c in classes:
            if c.is_abstract:
                continue
            for iface in self._class_interfaces(c.name):
                order = self.iface_decls[iface].methods
                slots = [
                    self._resolve_method(c.name, m.name)[1].bitcast(i8ptr) for m in order
                ]
                arr_ty = ir.ArrayType(i8ptr, len(order))
                g = ir.GlobalVariable(self.module, arr_ty, name=f"{c.name}${iface}.itable")
                g.global_constant = True
                g.linkage = "internal"
                g.initializer = ir.Constant(arr_ty, slots)
                self.itables[(c.name, iface)] = g


    def _full_fields(self, name: str) -> list:
        """A class's fields with inherited ones first (matches struct layout)."""
        if name in self._ff_cache:
            return self._ff_cache[name]
        c = self.class_decls[name]
        fields = list(self._full_fields(c.parent)) if c.parent else []
        fields += c.fields
        self._ff_cache[name] = fields
        return fields

    def _declare_class_types(self, classes: list[ClassDecl]) -> None:
        ctx = self.module.context
        for c in classes:
            self.class_decls[c.name] = c
            self.parents[c.name] = c.parent
            self.struct_types[c.name] = ctx.get_identified_type(c.name)
        for c in classes:
            full = self._full_fields(c.name)
            self.field_index[c.name] = {f.name: i + 1 for i, f in enumerate(full)}
            self.struct_types[c.name].set_body(
                vtable_ptr_ty, *[self._llvm_type(f.var_type) for f in full]
            )

    def _method_order(self, name: str) -> list[str]:
        """Vtable slot order for a class: base methods first, then new ones.

        Also fills self.vtable_index and self.method_sig for the class. Overrides
        keep their inherited slot; new methods append.
        """
        if name in self._mt_cache:
            return self._mt_cache[name]

        c = self.class_decls[name]
        order = list(self._method_order(c.parent)) if c.parent else []
        sig = dict(self.method_sig[c.parent]) if c.parent else {}

        for m in c.methods:
            if m.name not in sig:
                order.append(m.name)
            sig[m.name] = (
                self._ret_llvm(m.ret_type),
                [self._llvm_type(p.var_type) for p in m.params],
            )

        self._mt_cache[name] = order
        self.method_sig[name] = sig
        self.vtable_index[name] = {m: i for i, m in enumerate(order)}
        return order

    def _build_vtables(self, classes: list[ClassDecl]) -> None:
        for c in classes:
            self._method_order(c.name)
        for c in classes:
            if c.is_abstract:
                continue
            order = self._method_order(c.name)
            slots = [
                self._resolve_method(c.name, m)[1].bitcast(i8ptr) for m in order
            ]
            arr_ty = ir.ArrayType(i8ptr, len(order))
            g = ir.GlobalVariable(self.module, arr_ty, name=f"{c.name}.vtable")
            g.global_constant = True
            g.linkage = "internal"
            g.initializer = ir.Constant(arr_ty, slots)
            self.vtables[c.name] = g

    def _resolve_method(self, class_name: str, method: str):
        """Find (defining class, function) for `method`, climbing the base chain."""
        c: str | None = class_name
        while c is not None:
            fn = self.functions.get(self._mangle(c, method))
            if fn is not None:
                return c, fn
            c = self.parents.get(c)
        raise CodeGenError(f"no method {method!r} on class {class_name!r}")

    def _coerce(self, value: ir.Value, target_ty: ir.Type) -> ir.Value:
        """Convert a value to the target type at a subtype boundary:
        Dog* -> Animal* (bitcast), or a class object -> interface (fat pointer)."""
        if value.type == target_ty:
            return value
        if isinstance(target_ty, ir.IdentifiedStructType) and target_ty.name in self.iface_struct:
            return self._make_interface(value, target_ty.name)
        if isinstance(value.type, ir.PointerType) and isinstance(target_ty, ir.PointerType):
            return self.builder.bitcast(value, target_ty)
        return value

    def _make_interface(self, obj: ir.Value, iface: str) -> ir.Value:
        """Build an interface fat pointer {object, itable} from a class object."""
        class_name = obj.type.pointee.name
        obj_i8 = self.builder.bitcast(obj, i8ptr)
        itable = self.itables[(class_name, iface)]
        itable_ptr = self.builder.gep(
            itable, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True
        )
        fat = ir.Constant(self.iface_struct[iface], ir.Undefined)
        fat = self.builder.insert_value(fat, obj_i8, 0)
        fat = self.builder.insert_value(fat, itable_ptr, 1)
        return fat

    def _declare_class_members(self, classes: list[ClassDecl]) -> None:
        for c in classes:
            this_ty = self.struct_types[c.name].as_pointer()
            for m in c.methods:
                if m.is_abstract:
                    continue
                ret = self._ret_llvm(m.ret_type)
                params = [this_ty] + [self._llvm_type(p.var_type) for p in m.params]
                self._make_function(self._mangle(c.name, m.name), ret, params, m.params)
            if c.ctor is not None:
                params = [this_ty] + [self._llvm_type(p.var_type) for p in c.ctor.params]
                self._make_function(
                    self._mangle(c.name, c.name), ir.VoidType(), params, c.ctor.params
                )

    def _make_function(self, name, ret_ty, param_tys, params) -> ir.Function:
        fn = ir.Function(self.module, ir.FunctionType(ret_ty, param_tys), name=name)
        fn.args[0].name = "this"
        for arg, param in zip(fn.args[len(fn.args) - len(params):], params):
            arg.name = param.name
        self.functions[name] = fn
        return fn

    def _gen_class_members(self, classes: list[ClassDecl]) -> None:
        for c in classes:
            for m in c.methods:
                if m.is_abstract:
                    continue
                self._gen_callable(
                    self.functions[self._mangle(c.name, m.name)], m.body, has_this=True
                )
            if c.ctor is not None:
                self._gen_callable(
                    self.functions[self._mangle(c.name, c.name)], c.ctor.body, has_this=True
                )


    def _declare_function(self, func: FuncDecl) -> None:
        if func.name in self.functions:
            raise CodeGenError(f"function {func.name!r} already declared")
        ret_ty = self._ret_llvm(func.ret_type)
        param_tys = [self._llvm_type(p.var_type) for p in func.params]
        fn = ir.Function(self.module, ir.FunctionType(ret_ty, param_tys), name=func.name)
        for arg, param in zip(fn.args, func.params):
            arg.name = param.name
        self.functions[func.name] = fn

    def _begin_function(self, fn: ir.Function) -> ir.Block:
        """Set up entry/body blocks + a fresh local scope for `fn`."""
        entry_bb = fn.append_basic_block(name="entry")
        body_bb = fn.append_basic_block(name="body")
        self.alloca_builder = ir.IRBuilder(entry_bb)
        self.builder = ir.IRBuilder(body_bb)
        self.symbols = {}
        self.current_this = None
        self._depth_slot = self.alloca_builder.alloca(i32, name="gc_depth")
        self.builder.store(self.builder.call(self.gc_root_depth, []), self._depth_slot)
        return body_bb

    def _emit_root_restore(self) -> None:
        self.builder.call(self.gc_root_settop, [self.builder.load(self._depth_slot)])

    def _maybe_root(self, slot: ir.AllocaInstr) -> None:
        """Register a local slot as a GC root if it can hold heap references."""
        elem = slot.type.pointee
        if isinstance(elem, ir.PointerType):
            nwords = 1
        elif isinstance(elem, ir.IdentifiedStructType) and elem.name in self.iface_struct:
            nwords = 2
        else:
            return
        self.builder.call(
            self.gc_root_push,
            [self.builder.bitcast(slot, i8ptr), ir.Constant(i32, nwords)],
        )

    def _gen_callable(self, fn: ir.Function, body: list[Stmt], has_this: bool) -> None:
        body_bb = self._begin_function(fn)
        args = list(fn.args)
        if has_this:
            self.current_this = args[0]
            params = args[1:]
        else:
            params = args

        for arg in params:
            slot = self._alloca(arg.name, arg.type)
            self.builder.store(arg, slot)
            self.symbols[arg.name] = slot
            self._maybe_root(slot)

        self._gen_block(body)

        if not self.builder.block.is_terminated:
            self._emit_root_restore()
            ret_ty = fn.function_type.return_type
            if isinstance(ret_ty, ir.VoidType):
                self.builder.ret_void()
            else:
                self.builder.ret(self._zero(ret_ty))
        self.alloca_builder.branch(body_bb)

    def _gen_main(self, body: list[Stmt]) -> None:
        main = ir.Function(self.module, ir.FunctionType(i32, []), name="main")
        body_bb = self._begin_function(main)

        if body:
            self._gen_block(body)
        elif self._has_main_class():
            obj = self._gen_new(New("Main", []))
            _, fn = self._resolve_method("Main", "main")
            self.builder.call(fn, [obj])

        if not self.builder.block.is_terminated:
            self._emit_root_restore()
            self.builder.call(self.fflush, [ir.Constant(i8ptr, None)])
            self.builder.ret(ir.Constant(i32, 0))
        self.alloca_builder.branch(body_bb)

    def _has_main_class(self) -> bool:
        return (
            "Main" in self.struct_types
            and self._mangle("Main", "main") in self.functions
        )

    def _alloca(self, name: str, typ: ir.Type) -> ir.AllocaInstr:
        """Create a stack slot of `typ` in the current function's entry block."""
        return self.alloca_builder.alloca(typ, name=name)

    def _gen_block(self, stmts: list[Stmt]) -> None:
        for stmt in stmts:
            self._gen_stmt(stmt)

    def _as_bool(self, val: ir.Value) -> ir.Value:
        """Coerce a value to i1 for use as a condition (int x → x != 0)."""
        if val.type == i1:
            return val
        if val.type == i32:
            return self.builder.icmp_signed("!=", val, ir.Constant(i32, 0))
        raise CodeGenError(f"cannot use {val.type} as a condition")


    def _gen_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, VarDecl):
            if stmt.name in self.symbols:
                raise CodeGenError(f"variable {stmt.name!r} already declared")
            slot_ty = self._llvm_type(stmt.var_type)
            value = self._coerce(self._gen_expr(stmt.init), slot_ty)
            slot = self._alloca(stmt.name, slot_ty)
            self.builder.store(value, slot)
            self.symbols[stmt.name] = slot
            self._maybe_root(slot)
            return

        if isinstance(stmt, Assign):
            target = stmt.target
            if isinstance(target, Identifier):
                ptr = self.symbols[target.name]
            elif isinstance(target, Index):
                ptr = self._index_ptr(target)
            else:
                ptr = self._class_field_ptr(self._gen_expr(target.obj), target.field)
            value = self._coerce(self._gen_expr(stmt.value), ptr.type.pointee)
            self.builder.store(value, ptr)
            return

        if isinstance(stmt, SuperCall):
            class_name = self.current_this.type.pointee.name
            parent = self.parents[class_name]
            ctor = self.functions.get(self._mangle(parent, parent))
            if ctor is not None:
                this_arg = self._coerce(
                    self.current_this, self.struct_types[parent].as_pointer()
                )
                self.builder.call(ctor, [this_arg] + self._gen_args(stmt.args, ctor.args[1:]))
            return

        if isinstance(stmt, ExprStmt):
            self._gen_expr(stmt.expr)
            return

        if isinstance(stmt, PrintStmt):
            value = self._gen_expr(stmt.expr)
            if value.type == i8ptr:
                fmt = self._fmt_str
            else:
                if value.type == i1:
                    value = self.builder.zext(value, i32)
                fmt = self._fmt_int
            self.builder.call(self.printf, [self._str_ptr(fmt), value])
            return

        if isinstance(stmt, If):
            self._gen_if(stmt)
            return

        if isinstance(stmt, While):
            self._gen_while(stmt)
            return

        if isinstance(stmt, Return):
            if stmt.value is None:
                self._emit_root_restore()
                self.builder.ret_void()
            else:
                ret_ty = self.builder.function.function_type.return_type
                val = self._coerce(self._gen_expr(stmt.value), ret_ty)
                self._emit_root_restore()
                self.builder.ret(val)
            return

        raise CodeGenError(f"cannot codegen statement {type(stmt).__name__}")

    def _gen_if(self, stmt: If) -> None:
        cond = self._as_bool(self._gen_expr(stmt.cond))
        func = self.builder.function

        then_bb = func.append_basic_block("if.then")
        merge_bb = func.append_basic_block("if.end")
        else_bb = func.append_basic_block("if.else") if stmt.else_body else merge_bb

        self.builder.cbranch(cond, then_bb, else_bb)

        self.builder.position_at_end(then_bb)
        self._gen_block(stmt.then_body)
        if not self.builder.block.is_terminated:
            self.builder.branch(merge_bb)

        if stmt.else_body:
            self.builder.position_at_end(else_bb)
            self._gen_block(stmt.else_body)
            if not self.builder.block.is_terminated:
                self.builder.branch(merge_bb)

        self.builder.position_at_end(merge_bb)

    def _gen_while(self, stmt: While) -> None:
        func = self.builder.function
        cond_bb = func.append_basic_block("while.cond")
        body_bb = func.append_basic_block("while.body")
        end_bb = func.append_basic_block("while.end")

        self.builder.branch(cond_bb)
        self.builder.position_at_end(cond_bb)
        cond = self._as_bool(self._gen_expr(stmt.cond))
        self.builder.cbranch(cond, body_bb, end_bb)

        self.builder.position_at_end(body_bb)
        self._gen_block(stmt.body)
        if not self.builder.block.is_terminated:
            self.builder.branch(cond_bb)
        self.builder.position_at_end(end_bb)


    def _class_field_ptr(self, obj: ir.Value, field: str) -> ir.Value:
        """Pointer to obj.field, given an already-generated object pointer."""
        class_name = obj.type.pointee.name
        idx = self.field_index[class_name][field]
        return self.builder.gep(
            obj, [ir.Constant(i32, 0), ir.Constant(i32, idx)], inbounds=True
        )

    def _index_ptr(self, node: Index) -> ir.Value:
        """Pointer to arr[index], after a runtime bounds check."""
        arr = self._gen_expr(node.arr)
        idx = self._gen_expr(node.index)
        self._bounds_check(arr, idx)
        return self.builder.gep(
            arr, [ir.Constant(i32, 0), ir.Constant(i32, 1), idx], inbounds=True
        )

    def _bounds_check(self, arr: ir.Value, idx: ir.Value) -> None:
        """Abort with a message if idx is outside [0, arr.length)."""
        len_ptr = self.builder.gep(
            arr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True
        )
        length = self.builder.load(len_ptr)
        below = self.builder.icmp_signed("<", idx, ir.Constant(i32, 0))
        above = self.builder.icmp_signed(">=", idx, length)
        oob = self.builder.or_(below, above)

        func = self.builder.function
        err_bb = func.append_basic_block("oob")
        ok_bb = func.append_basic_block("inbounds")
        self.builder.cbranch(oob, err_bb, ok_bb)

        self.builder.position_at_end(err_bb)
        self.builder.call(self.printf, [self._str_ptr(self._oob_msg)])
        self.builder.call(self.exit, [ir.Constant(i32, 1)])
        self.builder.unreachable()

        self.builder.position_at_end(ok_bb)

    def _gen_expr(self, node: Expr) -> ir.Value:
        if isinstance(node, IntLiteral):
            return ir.Constant(i32, node.value)

        if isinstance(node, BoolLiteral):
            return ir.Constant(i1, 1 if node.value else 0)

        if isinstance(node, StringLiteral):
            data = bytearray(node.value.encode("utf-8")) + bytearray(b"\x00")
            g = self._global_string(bytes(data), f".str.{self._str_counter}")
            self._str_counter += 1
            return self._str_ptr(g)

        if isinstance(node, ThisExpr):
            return self.current_this

        if isinstance(node, Identifier):
            return self.builder.load(self.symbols[node.name], name=node.name)

        if isinstance(node, FieldAccess):
            obj = self._gen_expr(node.obj)
            if obj.type == i8ptr:
                return self.builder.trunc(self.builder.call(self.strlen, [obj]), i32)
            if isinstance(obj.type.pointee, ir.LiteralStructType):
                len_ptr = self.builder.gep(
                    obj, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True
                )
                return self.builder.load(len_ptr)
            return self.builder.load(self._class_field_ptr(obj, node.field))

        if isinstance(node, Index):
            return self.builder.load(self._index_ptr(node))

        if isinstance(node, New):
            return self._gen_new(node)

        if isinstance(node, NewArray):
            return self._gen_new_array(node)

        if isinstance(node, MethodCall):
            return self._gen_method_call(node)

        if isinstance(node, Call):
            if node.name not in self.functions:
                if node.name == "collect":
                    return self.builder.call(self.gc_collect, [])
                if node.name == "__live":
                    return self.builder.call(self.gc_live, [])
            fn = self.functions[node.name]
            return self.builder.call(fn, self._gen_args(node.args, fn.args))

        if isinstance(node, UnaryOp):
            operand = self._gen_expr(node.operand)
            return self.builder.sub(ir.Constant(i32, 0), operand)

        if isinstance(node, BinaryOp):
            left = self._gen_expr(node.left)
            right = self._gen_expr(node.right)
            if left.type == i8ptr:
                if node.op == "+":
                    return self._gen_concat(left, right)
                cmp = self.builder.call(self.strcmp, [left, right])
                op = "==" if node.op == "==" else "!="
                return self.builder.icmp_signed(op, cmp, ir.Constant(i32, 0))
            if node.op in _COMPARISONS:
                return self.builder.icmp_signed(node.op, left, right)
            match node.op:
                case "+":
                    return self.builder.add(left, right)
                case "-":
                    return self.builder.sub(left, right)
                case "*":
                    return self.builder.mul(left, right)
                case "/":
                    return self.builder.sdiv(left, right)
            raise CodeGenError(f"unknown operator {node.op!r}")

        raise CodeGenError(f"cannot codegen expression {type(node).__name__}")

    def _gen_new(self, node: New) -> ir.Value:
        struct = self.struct_types[node.class_name]
        ptr_ty = struct.as_pointer()

        size_ptr = self.builder.gep(ir.Constant(ptr_ty, None), [ir.Constant(i32, 1)])
        size = self.builder.ptrtoint(size_ptr, i64)

        raw = self.builder.call(self.gc_alloc, [size])
        obj = self.builder.bitcast(raw, ptr_ty)

        vtable = self.vtables[node.class_name]
        vtable_first = self.builder.gep(
            vtable, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True
        )
        vtable_field = self.builder.gep(
            obj, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True
        )
        self.builder.store(vtable_first, vtable_field)

        ctor = self.functions.get(self._mangle(node.class_name, node.class_name))
        if ctor is not None:
            self.builder.call(ctor, [obj] + self._gen_args(node.args, ctor.args[1:]))
        return obj

    def _gen_concat(self, a: ir.Value, b: ir.Value) -> ir.Value:
        """Concatenate two C strings into a freshly malloc'd buffer."""
        len_a = self.builder.call(self.strlen, [a])
        len_b = self.builder.call(self.strlen, [b])
        total = self.builder.add(
            self.builder.add(len_a, len_b), ir.Constant(i64, 1)
        )
        buf = self.builder.call(self.gc_alloc, [total])
        self.builder.call(self.strcpy, [buf, a])
        self.builder.call(self.strcat, [buf, b])
        return buf

    def _gen_new_array(self, node: NewArray) -> ir.Value:
        arr_ptr_ty = self._array_struct(node.elem_type).as_pointer()
        n = self._gen_expr(node.size)

        end = self.builder.gep(
            ir.Constant(arr_ptr_ty, None),
            [ir.Constant(i32, 0), ir.Constant(i32, 1), n],
        )
        size = self.builder.ptrtoint(end, i64)

        raw = self.builder.call(self.gc_alloc, [size])
        arr = self.builder.bitcast(raw, arr_ptr_ty)

        len_ptr = self.builder.gep(
            arr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True
        )
        self.builder.store(n, len_ptr)
        return arr

    def _gen_args(self, args: list, targets) -> list:
        """Generate call arguments, coercing each to its parameter type."""
        return [self._coerce(self._gen_expr(a), t.type) for a, t in zip(args, targets)]

    def _gen_method_call(self, node: MethodCall) -> ir.Value:
        """Dynamic dispatch. Through a class pointer it uses the object's vtable;
        through an interface value it uses the itable carried in the fat pointer."""
        obj = self._gen_expr(node.obj)
        if isinstance(obj.type, ir.IdentifiedStructType) and obj.type.name in self.iface_struct:
            return self._gen_interface_call(node, obj)

        static_class = obj.type.pointee.name
        slot = self.vtable_index[static_class][node.method]
        ret_ty, param_tys = self.method_sig[static_class][node.method]

        vtable_field = self.builder.gep(
            obj, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True
        )
        vtable = self.builder.load(vtable_field)
        slot_ptr = self.builder.gep(vtable, [ir.Constant(i32, slot)], inbounds=True)
        fn_generic = self.builder.load(slot_ptr)

        fn_ty = ir.FunctionType(ret_ty, [obj.type, *param_tys])
        fn_ptr = self.builder.bitcast(fn_generic, fn_ty.as_pointer())

        args = [obj] + [
            self._coerce(self._gen_expr(a), t) for a, t in zip(node.args, param_tys)
        ]
        return self.builder.call(fn_ptr, args)

    def _gen_interface_call(self, node: MethodCall, fat: ir.Value) -> ir.Value:
        """Call a method through an interface fat pointer {object, itable}."""
        iface = fat.type.name
        slot = self.iface_index[iface][node.method]
        ret_ty, param_tys = self.iface_sig[iface][node.method]

        obj_i8 = self.builder.extract_value(fat, 0)
        itable = self.builder.extract_value(fat, 1)
        slot_ptr = self.builder.gep(itable, [ir.Constant(i32, slot)], inbounds=True)
        fn_generic = self.builder.load(slot_ptr)

        fn_ty = ir.FunctionType(ret_ty, [i8ptr, *param_tys])
        fn_ptr = self.builder.bitcast(fn_generic, fn_ty.as_pointer())
        args = [obj_i8] + [
            self._coerce(self._gen_expr(a), t) for a, t in zip(node.args, param_tys)
        ]
        return self.builder.call(fn_ptr, args)


def build_module(program: list) -> ir.Module:
    """Build a module with `i32 @main()` running `program`."""
    return CodeGen().generate(program)
