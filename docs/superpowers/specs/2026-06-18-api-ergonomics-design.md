# API Ergonomics: String Interpolation + `toJson()` — Design

## Goal

Two ergonomic wins for backend code, shipped together:

1. **String interpolation** — `"hi ${user.name}, ${n + 1} items"` instead of
   manual `+`/`toString` chains.
2. **Object → JSON** — every class gets an auto-synthesized `toJson()` returning
   a JSON string, so `req.respondJson(200, user.toJson())` just works.

(JSON → object *deserialize* is explicitly deferred to a later milestone — it
needs static methods or generic functions, which Tawla lacks.)

## Shared change: universal `toString`

`toString(x)` today accepts only int/float. Extend it to a universal
stringifier:

- `string` → returned unchanged.
- `bool` → `"true"` / `"false"`.
- `int` / `float` → as today (decimal text).

This is needed by interpolation (which wraps every embedded expression in
`toString`) and is useful on its own. Changes: sema `toString` accepts
`{INT, FLOAT, BOOL, STRING}` (still arity 1, still returns `STRING`); codegen
`toString` handles the new cases (string → identity pointer; bool → select
between `"true"`/`"false"` globals).

## Component 1: String interpolation

### Syntax

`${expr}` is active inside **every** `"..."` string literal. A bare `$` not
followed by `{` is a literal `$` (so `"$5.00"` is unchanged). `expr` is any
Tawla expression: `"hi ${user.name}, ${n + 1} items"`.

### Desugaring

An interpolated string becomes a `+`-concatenation of string literals and
`toString`-wrapped expressions:

```
"a${x}b${y}"  →  "a" + toString(x) + "b" + toString(y)
```

Every part is `string`-typed (literals are strings; `toString(...)` returns
string), so the existing `+` (string-concat) sema/codegen handle it with **no
interpolation-specific sema or codegen changes**.

### Mechanism

- **Lexer** (`tawla/lexer.py`): when scanning a string literal, if a `${` is
  present, split the content into ordered parts — alternating *literal chunks*
  (with the usual escape processing) and *raw expression source* captured
  between `${` and its matching `}`. Matching tracks `{`/`}` depth and skips over
  `"`-quoted substrings inside the expression (so `${ f("}") }` works). Emit a
  new token kind `INTERP` carrying the parts list. A string with no `${` emits a
  normal `STRING` token (unchanged behavior).
- **Parser** (`tawla/parser.py`): when the primary parser sees an `INTERP`
  token, for each expression-source part it sub-parses an expression
  (`tokenize` the source → a fresh `Parser` → `.expr()`, requiring it to consume
  to EOF), and assembles a left-folded `BinaryOp("+", ...)` tree of
  `StringLiteral` (for literal chunks) and `Call("toString", [expr])` (for
  expression parts). A leading/trailing/again literal chunk that is empty is
  dropped, except an all-empty interpolation still yields `StringLiteral("")`.
  An empty `${}` (no expression source) is a `ParseError`.

### AST / tokens

- `tokens.py`: add `TokenKind.INTERP`. The token carries `parts` — a list of
  `("lit", str)` and `("expr", str)` tuples.
- No new AST node: interpolation lowers to existing `BinaryOp`/`StringLiteral`/
  `Call` nodes in the parser.

## Component 2: Object → JSON (`toJson()`)

### Behavior

Every class automatically gets a method `string toJson()` **unless it already
declares one** (a user-defined `toJson` wins). It returns a JSON object string
over the class's declared **and inherited** fields, in declaration order:

```
{"field1":<json1>,"field2":<json2>,...}
```

Per-field serialization by static field type:

| Field type | JSON |
|------------|------|
| `int`, `float` | `toString(this.f)` (a JSON number) |
| `bool` | `this.f ? "true" : "false"` |
| `string` | `__json_escape(this.f)` (quoted+escaped; `null` → `null`) |
| class (object) | `this.f == null ? "null" : this.f.toJson()` |
| array `T[]` | `[e0,e1,...]` — each element serialized by `T`'s rule; `null` array → `null` |

`toJson` is a normal (virtual) method, so a nested field holding a subclass
instance serializes the subclass's `toJson`.

### Mechanism — synthesized AST

A new compiler pass, `tawla/tojson.py`, runs **after monomorphize, before sema**
(so field types are concrete and the synthesized methods get type-checked). For
each `ClassDecl` lacking a `toJson` method, it appends a synthesized
`MethodDecl("toJson", params=[], ret_type="string", body=[...])` whose body is
ordinary Tawla AST that builds the JSON string:

- a local `string result = "{"` accumulator, appended per field, then `+ "}"`,
  `return result;`
- numeric/bool/string/object fields → the expressions in the table above;
- array fields → a synthesized `while` loop over `this.f.length` with an `int i`
  index, an `if (i > 0) { ... + "," }` separator, appending each element's JSON,
  wrapped in `[`…`]`; a `this.f == null` guard emits `null`.

Because the body is normal AST, **sema type-checks it and codegen emits it with
no special-casing**, and it slots into the vtable like any method.

### New builtin: `__json_escape`

`__json_escape(s: string) -> string` — returns a JSON-quoted, escaped string
(e.g. `Python json.dumps(s)`), or the literal `null` when `s` is `null`. Hosted
in `tawla/str_runtime.py` (string-manipulation runtime), wired in sema
(`([STRING], STRING)`) and codegen like the other string builtins. The
synthesized `toJson` uses it for string fields/elements.

## Components / files

- `tawla/tokens.py` — `INTERP` token kind.
- `tawla/lexer.py` — split interpolated strings into parts.
- `tawla/parser.py` — assemble the concat from an `INTERP` token.
- `tawla/sema.py` — universal `toString`; declare `__json_escape`.
- `tawla/codegen.py` — `toString` string/bool cases; declare + dispatch
  `__json_escape`.
- `tawla/str_runtime.py` — `__json_escape` implementation + registration.
- `tawla/tojson.py` — new pass synthesizing `toJson` MethodDecls.
- `tawla/compiler.py` — run the `tojson` pass after monomorphize.
- `tests/test_m40.py`; `examples/ergonomics.twl`; README + docs; version → 1.9.0.

## Testing (`tests/test_m40.py`)

**Interpolation:**
- `"a${1 + 2}b"` → `"a3b"`; `string n = "Ada"; "hi ${n}"` → `"hi Ada"`.
- bool/float embeds: `"${true}"` → `"true"`, `"${1.5}"` → `"1.5"`.
- expression inside: `"${x}-${x * 2}"`.
- bare `$`: `"$5.00"` → `"$5.00"` (literal, unchanged).
- nested member/call: `"len ${s.length}"`.
- plain strings still work; escapes still work (`"a\tb"`).
- universal `toString`: `toString("x")` → `"x"`, `toString(true)` → `"true"`.

**toJson:**
- flat class: `{"id":1,"name":"Ada","active":true}` (field order, escaping).
- string escaping: a field containing a quote/newline is escaped.
- null string field → `null`; null object field → `null`.
- nested object: `{"name":"Ada","addr":{"city":"NYC"}}`.
- array field: `int[]` → `[1,2,3]`; array of objects → `[{...},{...}]`.
- inherited fields included.
- user-defined `toJson` is not overwritten.
- round-trips through `Json.twl` `parseJson(user.toJson())` reads a field back.

## Out of scope

- JSON → object deserialize (`fromJson`) — separate later milestone.
- `List<T>` / `Map<K,V>` fields in `toJson` (they serialize their internal
  struct; documented — use arrays for JSON DTOs).
- Reference cycles (undefined / would recurse).
- Multi-dimensional arrays.
- A literal `${` escape inside strings (use string concatenation if needed).
