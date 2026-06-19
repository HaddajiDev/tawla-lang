# API Ergonomics (String Interpolation + `toJson()`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `${expr}` string interpolation and an auto-synthesized `toJson()` on every class.

**Architecture:** Interpolation is lexer-split + parser-desugared to `lit + toString(expr) + …` (no sema/codegen changes beyond a universal `toString`). `toJson()` is produced by a new compiler pass that synthesizes the method body as ordinary Tawla AST after monomorphize, so sema/codegen handle it unchanged; a `__json_escape` builtin handles string escaping.

**Tech Stack:** Python 3.11+, llvmlite, the Tawla compiler, pytest.

## Global Constraints

- Use `venv/Scripts/python.exe`; tests via `venv/Scripts/python.exe -m pytest`.
- Final version: `1.9.0` (`pyproject.toml` line 3, `tawla/__init__.py` line 3).
- Deserialize (`fromJson`) is OUT OF SCOPE.

**Reference spec:** `docs/superpowers/specs/2026-06-18-api-ergonomics-design.md`

---

## Verified facts (from the codebase)

- codegen type constants: `i32`, `i1` (bool), `i8ptr`, `f64`. `self._global_string(b"..\0", "name")` makes a global; `self._str_ptr(g)` yields its `i8ptr`. `self.builder.select(cond, a, b)` is available. `toString` codegen lives in the builtin dispatch (`if name == "toString":`, ~line 1156) and currently handles f64/i32 via `num_to_str_f`/`num_to_str_i`.
- sema `_check_builtin` has `if name == "toString": self._check_numeric(name, args, 1); return STRING` (~line 763). Constants `INT/FLOAT/BOOL/STRING` exist.
- `_BUILTINS` dict maps `name -> (params, ret)`. codegen externs declared near other runtime fns; dispatched in the `if name == "...":` chain.
- `str_runtime.py`: `_alloc(s)` GC-allocs a string; `_c_*` CFUNCTYPE wrappers; `install()` `add_symbol`s `num_to_str_i`/`num_to_str_f`. It's already in `compiler.py`'s runtime install list, so adding a symbol there needs no compiler change.
- Lexer string branch (`if c == '"':`, ~lines 83-101) decodes escapes into `chars` and emits `Token(TokenKind.STRING, value, start)`. `Token` is a dataclass `Token(kind, text=None, pos=0)` in `tokens.py`. `_ESCAPES` maps escape chars.
- Parser: `primary()` (~641) turns a `STRING` token into `StringLiteral(tok.text)` (~652). `parse(tokens)` is the module entry; a `Parser` is constructed from a token list and exposes `.expr()` and `.current`. `from .lexer import tokenize` is available.
- AST nodes (in `ast_nodes.py`): `ThisExpr()`, `Identifier(name)`, `Index(arr, index)`, `FieldAccess(obj, field)`, `MethodCall(obj, method, args)`, `Call(name, args)`, `BinaryOp(op, left, right)`, `Ternary(cond, then_expr, else_expr, result_type=None)`, `If(cond, then_body, else_body)`, `While(cond, body)`, `Assign(target, value)`, `VarDecl(var_type, name, init)`, `Return(value)`, `IntLiteral(value)`, `StringLiteral(value)`, `NullLiteral()`, `MethodDecl(ret_type, name, params, body, is_abstract=False, visibility="private")`, `ClassDecl(name, fields, methods, ctor, bases=[], is_abstract=False, type_params=[], parent=None, interfaces=[])`, `FieldDecl` has `.name` and `.var_type`.
- Pipeline: `compiler.py` `_run_items` (~64) does `ast = monomorphize(ast); type_check(ast); module = build_module(ast)`. `parent` on `ClassDecl` may be unset before sema — use `bases` (filter to entries that name a class) to find inherited fields.
- Array element `.length` and `arr[i]` are `FieldAccess(arr, "length")` and `Index(arr, i)`; arrays are single-dimensional with type strings like `"int[]"`.

## File Structure

| File | Change |
|------|--------|
| `tawla/sema.py` | universal `toString`; declare `__json_escape` |
| `tawla/codegen.py` | `toString` string/bool cases (+ `true`/`false` globals); declare+dispatch `__json_escape` |
| `tawla/str_runtime.py` | `__json_escape` impl + registration |
| `tawla/tokens.py` | `INTERP` token kind; `parts` field on `Token` |
| `tawla/lexer.py` | split interpolated strings into parts |
| `tawla/parser.py` | assemble concat from an `INTERP` token |
| `tawla/tojson.py` | NEW — synthesize `toJson` MethodDecls |
| `tawla/compiler.py` | run the tojson pass after monomorphize |
| `tests/test_m40.py`; `examples/ergonomics.twl`; README; docs; version | tests, example, docs |

---

## Task 1: Universal `toString` (string + bool)

**Files:** Modify `tawla/sema.py`, `tawla/codegen.py`; test `tests/test_m40.py`.

**Interfaces — Produces:** `toString(x)` accepts `int/float/bool/string` → `string`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_m40.py`:

```python
"""M40: API ergonomics — string interpolation + toJson()."""


def test_tostring_universal(run_twl):
    src = (
        "class Main { void main() {"
        ' print(toString("x")); print(toString(true)); print(toString(false));'
        " print(toString(42)); print(toString(1.5)); } }"
    )
    assert run_twl(src).stdout == "x\ntrue\nfalse\n42\n1.5\n"
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_m40.py -v`
Expected: FAIL — `toString("x")`/`toString(true)` rejected by sema.

- [ ] **Step 3: Loosen `toString` in sema**

In `tawla/sema.py`, replace the `toString` builtin check:

```python
        if name == "toString":
            self._check_numeric(name, args, 1)
            return STRING
```

with:

```python
        if name == "toString":
            if len(args) != 1:
                raise SemaError(f"'toString' expects 1 argument, got {len(args)}")
            t = self._check_expr(args[0])
            if t not in (INT, FLOAT, BOOL, STRING):
                raise SemaError(f"toString expects int, float, bool, or string, got {t}")
            return STRING
```

- [ ] **Step 4: Add `true`/`false` string globals**

In `tawla/codegen.py`, where other globals like `_fmt_str` are created, add:

```python
        self._true_str = self._global_string(b"true\0", "true_str")
        self._false_str = self._global_string(b"false\0", "false_str")
```

- [ ] **Step 5: Handle string/bool in `toString` codegen**

In `tawla/codegen.py`, replace the `toString` dispatch:

```python
        if name == "toString":
            v = self._gen_expr(args[0])
            if v.type == f64:
                return self.builder.call(self.num_to_str_f, [v])
            return self.builder.call(self.num_to_str_i, [v])
```

with:

```python
        if name == "toString":
            v = self._gen_expr(args[0])
            if v.type == f64:
                return self.builder.call(self.num_to_str_f, [v])
            if v.type == i8ptr:
                return v  # already a string
            if v.type == i1:
                return self.builder.select(
                    v, self._str_ptr(self._true_str), self._str_ptr(self._false_str)
                )
            return self.builder.call(self.num_to_str_i, [v])
```

- [ ] **Step 6: Run the test**

Run: `venv/Scripts/python.exe -m pytest tests/test_m40.py::test_tostring_universal -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tawla/sema.py tawla/codegen.py tests/test_m40.py
git commit -m "toString: universal stringifier (string identity + bool true/false)"
```

---

## Task 2: String interpolation

**Files:** Modify `tawla/tokens.py`, `tawla/lexer.py`, `tawla/parser.py`; test `tests/test_m40.py`.

**Interfaces — Consumes:** universal `toString` (Task 1). **Produces:** `${expr}` in string literals desugars to `lit + toString(expr) + …`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_m40.py`:

```python
def test_interp_basic(run_twl):
    src = (
        "class Main { void main() {"
        ' string n = "Ada"; int x = 3;'
        ' print("hi ${n}, ${x + 1} items");'
        ' print("${true}|${1.5}|$5.00"); } }'
    )
    assert run_twl(src).stdout == "hi Ada, 4 items\ntrue|1.5|$5.00\n"


def test_interp_plain_and_escapes(run_twl):
    src = 'class Main { void main() { print("a\\tb"); print("no interp here"); } }'
    assert run_twl(src).stdout == "a\tb\nno interp here\n"
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_m40.py -k interp -v`
Expected: FAIL — `${n}` is currently treated as literal text, so output differs.

- [ ] **Step 3: Add the `INTERP` token + `parts` field**

In `tawla/tokens.py`, add `INTERP = auto()` to `TokenKind`, and add a `parts`
field to the `Token` dataclass:

```python
@dataclass
class Token:
    kind: TokenKind
    text: str | None = None
    pos: int = 0
    parts: list | None = None
```

- [ ] **Step 4: Split interpolated strings in the lexer**

In `tawla/lexer.py`, replace the whole `if c == '"':` string-scanning branch
(the block that builds `chars` and appends a `STRING` token) with:

```python
        if c == '"':
            start = i
            i += 1
            parts: list = []
            buf: list[str] = []
            has_expr = False
            while i < n and src[i] != '"':
                if src[i] == "\\":
                    i += 1
                    if i >= n:
                        raise LexError(f"unterminated escape in string at position {start}")
                    esc = _ESCAPES.get(src[i])
                    if esc is None:
                        raise LexError(f"unknown escape '\\{src[i]}' at position {i}")
                    buf.append(esc)
                    i += 1
                elif src[i] == "$" and i + 1 < n and src[i + 1] == "{":
                    parts.append(("lit", "".join(buf)))
                    buf = []
                    has_expr = True
                    i += 2  # past "${"
                    expr_start = i
                    depth = 1
                    while i < n and depth > 0:
                        ch = src[i]
                        if ch == '"':
                            i += 1
                            while i < n and src[i] != '"':
                                if src[i] == "\\":
                                    i += 1
                                i += 1
                            i += 1  # past closing quote
                            continue
                        if ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1
                            if depth == 0:
                                break
                        i += 1
                    if depth != 0:
                        raise LexError(f"unterminated ${{...}} in string at position {start}")
                    parts.append(("expr", src[expr_start:i]))
                    i += 1  # past closing "}"
                else:
                    buf.append(src[i])
                    i += 1
            if i >= n:
                raise LexError(f"unterminated string literal at position {start}")
            i += 1  # past closing quote
            if has_expr:
                parts.append(("lit", "".join(buf)))
                tokens.append(Token(TokenKind.INTERP, None, start, parts=parts))
            else:
                tokens.append(Token(TokenKind.STRING, "".join(buf), start))
            continue
```

- [ ] **Step 5: Assemble the concat in the parser**

In `tawla/parser.py`, ensure `from .lexer import tokenize` is imported (add it if
absent). In `primary()`, add an `INTERP` case alongside the `STRING` case:

```python
        if tok.kind is TokenKind.INTERP:
            self.advance()
            return self._build_interp(tok.parts)
```

Add these methods to the parser class:

```python
    def _build_interp(self, parts) -> Expr:
        node: Expr | None = None
        for kind, text in parts:
            if kind == "lit":
                if text == "":
                    continue
                piece: Expr = StringLiteral(text)
            else:
                piece = Call("toString", [self._parse_interp_expr(text)])
            node = piece if node is None else BinaryOp("+", node, piece)
        return node if node is not None else StringLiteral("")

    def _parse_interp_expr(self, src: str) -> Expr:
        sub = Parser(tokenize(src))
        if sub.current.kind is TokenKind.EOF:
            raise ParseError("empty '${}' interpolation")
        expr = sub.expr()
        if sub.current.kind is not TokenKind.EOF:
            raise ParseError(f"unexpected tokens in interpolation: {src!r}")
        return expr
```

(`Call` and `BinaryOp` are already imported in `parser.py`; if `Call` is not,
add it to the `ast_nodes` import. `Parser` is this class — reference it by its
actual class name as defined in the file.)

- [ ] **Step 6: Run the interpolation tests**

Run: `venv/Scripts/python.exe -m pytest tests/test_m40.py -k interp -v`
Expected: PASS.

- [ ] **Step 7: Run the full suite (no regressions in existing string handling)**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all pass (plain strings/escapes unaffected).

- [ ] **Step 8: Commit**

```bash
git add tawla/tokens.py tawla/lexer.py tawla/parser.py tests/test_m40.py
git commit -m "String interpolation: lex ${expr}, desugar to + / toString"
```

---

## Task 3: `__json_escape` builtin

**Files:** Modify `tawla/str_runtime.py`, `tawla/sema.py`, `tawla/codegen.py`; test `tests/test_m40.py`.

**Interfaces — Produces:** `__json_escape(s: string) -> string` (quoted+escaped; `null` → `null`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_m40.py`:

```python
def test_json_escape(run_twl):
    src = (
        "class Main { void main() {"
        ' print(__json_escape("hi"));'
        ' string z; print(__json_escape(z)); } }'   # null -> null
    )
    assert run_twl(src).stdout == '"hi"\nnull\n'
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_m40.py::test_json_escape -v`
Expected: FAIL — `__json_escape` unknown.

- [ ] **Step 3: Implement in `str_runtime.py`**

In `tawla/str_runtime.py`, add `import json` at the top, then after the existing
`_c_from_float` line add:

```python
def _json_escape(b):
    if b is None:
        return _alloc("null")
    return _alloc(json.dumps(b.decode("utf-8")))


_c_json_escape = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p)(lambda b: _json_escape(b))
```

Add `_c_json_escape` to the `_CALLBACKS` list, and in `install()` add:

```python
    llvm.add_symbol("__json_escape", cast(_c_json_escape, ctypes.c_void_p).value)
```

(If `install()` doesn't already bind `cast = ctypes.cast`, use `ctypes.cast(...)`
directly to match the file's style.)

- [ ] **Step 4: Declare in sema**

In `tawla/sema.py` `_BUILTINS`, add:

```python
    "__json_escape": ([STRING], STRING),
```

- [ ] **Step 5: Declare + dispatch in codegen**

In `tawla/codegen.py`, near the other string externs, add:

```python
        self.json_escape = ir.Function(self.module, ir.FunctionType(i8ptr, [i8ptr]), name="__json_escape")
```

and in the builtin dispatch chain add:

```python
        if name == "__json_escape":
            return self.builder.call(self.json_escape, [self._gen_expr(args[0])])
```

- [ ] **Step 6: Run the test**

Run: `venv/Scripts/python.exe -m pytest tests/test_m40.py::test_json_escape -v`
Expected: PASS (`"hi"` then `null`).

- [ ] **Step 7: Commit**

```bash
git add tawla/str_runtime.py tawla/sema.py tawla/codegen.py tests/test_m40.py
git commit -m "Add __json_escape builtin (JSON string escaping)"
```

---

## Task 4: `toJson()` synthesis pass

**Files:** Create `tawla/tojson.py`; modify `tawla/compiler.py`; test `tests/test_m40.py`.

**Interfaces — Consumes:** `toString` (Task 1), `__json_escape` (Task 3). **Produces:** every `ClassDecl` without a `toJson` gains `string toJson()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_m40.py`:

```python
def _prog(body, classes=""):
    return classes + " class Main { void main() { " + body + " } }"


def test_tojson_flat(run_twl):
    classes = (
        "class User {"
        " public int id; public string name; public bool active;"
        " public User(int id, string name, bool active) {"
        "   this.id = id; this.name = name; this.active = active; } }"
    )
    body = 'User u = new User(1, "Ada", true); print(u.toJson());'
    assert run_twl(_prog(body, classes)).stdout == '{"id":1,"name":"Ada","active":true}\n'


def test_tojson_string_escaping_and_null(run_twl):
    classes = (
        "class Box { public string a; public string b;"
        " public Box(string a) { this.a = a; } }"
    )
    # b is left null
    body = 'Box x = new Box("he\\"llo"); print(x.toJson());'
    assert run_twl(_prog(body, classes)).stdout == '{"a":"he\\"llo","b":null}\n'


def test_tojson_nested_object(run_twl):
    classes = (
        "class Addr { public string city; public Addr(string c) { this.city = c; } }"
        " class Person { public string name; public Addr addr;"
        "   public Person(string n, Addr a) { this.name = n; this.addr = a; } }"
    )
    body = 'Person p = new Person("Ada", new Addr("NYC")); print(p.toJson());'
    assert run_twl(_prog(body, classes)).stdout == '{"name":"Ada","addr":{"city":"NYC"}}\n'


def test_tojson_array(run_twl):
    classes = (
        "class Bag { public int[] xs;"
        " public Bag() { this.xs = new int[3]; this.xs[0]=1; this.xs[1]=2; this.xs[2]=3; } }"
    )
    body = "Bag b = new Bag(); print(b.toJson());"
    assert run_twl(_prog(body, classes)).stdout == '{"xs":[1,2,3]}\n'


def test_tojson_user_defined_wins(run_twl):
    classes = (
        'class C { public int n; public C() { this.n = 5; }'
        ' public string toJson() { return "custom"; } }'
    )
    body = "C c = new C(); print(c.toJson());"
    assert run_twl(_prog(body, classes)).stdout == "custom\n"
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/Scripts/python.exe -m pytest tests/test_m40.py -k tojson -v`
Expected: FAIL — classes have no `toJson` (sema: "type ... has no method toJson").

- [ ] **Step 3: Create the synthesis pass**

Create `tawla/tojson.py`:

```python
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


def _all_fields(c, classes):
    fields = []
    for base in c.bases:
        if base in classes:
            fields.extend(_all_fields(classes[base], classes))
    fields.extend(c.fields)
    return fields


def _append(stmts, expr):
    # __json = __json + expr
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
        # a known class: recurse via its (synthesized or user) toJson, null-guarded
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
                If(BinaryOp("==", field, NullLiteral()),
                   [Assign(Identifier("__json"), BinaryOp("+", Identifier("__json"), StringLiteral("null")))],
                   inner)
            )
        else:
            _append(stmts, _value_expr(field, f.var_type, classes))
    _append(stmts, StringLiteral("}"))
    stmts.append(Return(Identifier("__json")))
    return MethodDecl("string", "toJson", [], stmts, False, "public")
```

- [ ] **Step 4: Wire the pass into the compiler**

In `tawla/compiler.py`, add the import and run the pass between monomorphize and
type_check in `_run_items`:

```python
from .tojson import synthesize_tojson
```

```python
    ast = monomorphize(ast)
    ast = synthesize_tojson(ast)
    type_check(ast)
    module = build_module(ast)
```

- [ ] **Step 5: Run the toJson tests**

Run: `venv/Scripts/python.exe -m pytest tests/test_m40.py -k tojson -v`
Expected: PASS (flat, escaping/null, nested, array, user-defined-wins).

- [ ] **Step 6: Run the full suite**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: all pass. (Synthesizing toJson on every class must not break existing
programs — the method is added but unused unless called.)

- [ ] **Step 7: Commit**

```bash
git add tawla/tojson.py tawla/compiler.py tests/test_m40.py
git commit -m "Synthesize toJson() on every class (AST pass after monomorphize)"
```

---

## Task 5: Example, docs, version, verification

**Files:** Create `examples/ergonomics.twl`; modify `README.md`, `tawla_lang_docs/index.html`, `pyproject.toml`, `tawla/__init__.py`.

- [ ] **Step 1: Create the example**

Create `examples/ergonomics.twl`:

```tawla
// String interpolation + automatic JSON serialization.
class User {
    public int id;
    public string name;
    public string[] roles;
    public User(int id, string name, string[] roles) {
        this.id = id; this.name = name; this.roles = roles;
    }
}

class Main {
    void main() {
        string[] roles = new string[2];
        roles[0] = "admin"; roles[1] = "user";
        User u = new User(7, "Ada", roles);

        // interpolation
        print("user ${u.name} has id ${u.id} and ${u.roles.length} roles");

        // every class can serialize itself to JSON
        print(u.toJson());
    }
}
```

- [ ] **Step 2: Verify the example runs**

Run: `venv/Scripts/python.exe -m tawla run examples/ergonomics.twl`
Expected:
```
user Ada has id 7 and 2 roles
{"id":7,"name":"Ada","roles":["admin","user"]}
```

- [ ] **Step 3: Update the README**

In `README.md`, add two bullets in the "What the language can do" list:

```markdown
- **String interpolation:** `"hi ${user.name}, ${n + 1} items"` inside any
  string literal (a bare `$` is literal). Embedded expressions are stringified
  with `toString`, which now also handles `bool` and `string`.
- **JSON serialization:** every class has an auto-generated `toJson()` returning
  a JSON string over its fields (primitives, nested objects, and arrays) —
  `req.respondJson(200, user.toJson())`. (JSON → object parsing is via
  `Json.twl`.)
```

- [ ] **Step 4: Update the docs site**

In `tawla_lang_docs/index.html`, add a `#ergonomics` section after `#essentials`
(and a sidebar link `<a href="#ergonomics">Interpolation &amp; JSON</a>`).
Intro + this example (escape `<`/`>`/`&`):

```html
    <section id="ergonomics">
      <h2>Interpolation &amp; JSON</h2>
      <p>String literals interpolate <code>${expr}</code> (a bare <code>$</code> is literal). And every class has an auto-generated <code>toJson()</code> that serializes its fields — primitives, nested objects, and arrays — so returning JSON is one call.</p>
      <div class="code">
        <div class="code-head"><span class="dot"></span><span class="fname">ergonomics.twl</span><button class="copy-btn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg><span class="copy-label">Copy</span></button></div>
        <pre><code class="twl">print("hi ${user.name}, ${n + 1} items");

// every class can serialize itself
req.respondJson(200, user.toJson());   // {"id":7,"name":"Ada",...}</code></pre>
      </div>
    </section>
```

- [ ] **Step 5: Bump version to 1.9.0**

`pyproject.toml` line 3 → `version = "1.9.0"`; `tawla/__init__.py` line 3 →
`__version__ = "1.9.0"`.

- [ ] **Step 6: Full suite + version + frozen smoke**

Run: `venv/Scripts/python.exe -m pytest -q` → all pass.
Run: `venv/Scripts/python.exe -m tawla version` → `tawlac 1.9.0`.
Rebuild + smoke:
```bash
venv/Scripts/pyinstaller.exe tawlac.spec --clean --noconfirm
./dist/tawlac.exe run examples/ergonomics.twl
```
Expected: the interpolation line + `{"id":7,"name":"Ada","roles":["admin","user"]}`.

- [ ] **Step 7: Commit (compiler) + push docs**

```bash
git add examples/ergonomics.twl README.md pyproject.toml tawla/__init__.py
git commit -m "Add ergonomics example, docs; bump to 1.9.0"
```

```bash
cd D:\Projects\tawla_lang_docs
git add index.html
git commit -m "Document string interpolation and toJson()"
git push
cd D:\Projects\Tawla_lang
```

---

## Done criteria

- `"a${x}b"` interpolates; `toString` handles string/bool; plain strings/escapes unaffected.
- Every class has `toJson()` serializing primitives, strings (escaped), bool, nested objects (null→null), and arrays; user-defined `toJson` wins.
- `__json_escape` works; `tests/test_m40.py` + full suite green; `tawlac version` → `1.9.0`; frozen binary runs `ergonomics.twl`.

## Release (on the user's go-ahead)

Merge to `main`, push, `git tag v1.9.0 && git push origin v1.9.0`, then build +
publish 1.9.0 to PyPI.
