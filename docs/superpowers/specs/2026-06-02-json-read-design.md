# Design: JSON read (Json value + parseJson)

Status: approved (brainstorm) — pending implementation
Date: 2026-06-02
Milestone: M32 — additive, ships as **1.3.0** (with string utils + JSON write)

## Goal

Parse JSON text into a navigable value, all in Tawla. This is the read half of
JSON; the write half (builders + `toString` + `respondJson`) is a following
milestone. Backends use this to read request bodies.

## The Json value

One class in the bundled `Json.twl` (which `import "Collections.twl";` for
`List`/`Map`). A kind tag plus storage for each possible payload:

```tawla
class Json {
    int kind;                 // 0 null, 1 bool, 2 number, 3 string, 4 array, 5 object
    bool boolVal;
    float numVal;
    string strVal;
    List<Json> arr;
    Map<string, Json> obj;
}
```

A bare `new Json()` is a `null` value (kind 0, fields zero/null) — also what
`get` returns for a missing key, so navigation chains stay safe.

### Read API (instance methods, all `public`)

- Type checks: `isNull()`, `isBool()`, `isNumber()`, `isString()`, `isArray()`,
  `isObject()` → `bool` (compare `kind`).
- Scalars: `asBool() -> bool` (`boolVal`), `asFloat() -> float` (`numVal`),
  `asString() -> string` (`strVal`), `asInt() -> int`
  (`toInt(toString(this.numVal))` — round-trips the float; fine for ids/counts,
  with huge-integer precision a documented edge).
- `size() -> int` — `arr.size()` for an array, `obj.size()` for an object, else
  `0`.
- `at(int i) -> Json` — array element when this is an array
  (`this.kind == 4`): delegates to `List.get`, so an out-of-range index hits the
  list's `panic`; on a non-array, returns a null `Json`.
- `get(string key) -> Json` — object field. Returns `obj.get(key)` when this is
  an object **and** the key is present (`this.kind == 5 && this.obj.has(key)` —
  the short-circuit `&&` means `obj` is never touched on a non-object), otherwise
  a fresh `new Json()` (a null value). So `get` never crashes on the wrong kind.

```tawla
Json d = parseJson("{\"name\":\"ada\",\"age\":36,\"tags\":[\"x\",\"y\"],\"ok\":true}");
d.get("name").asString();        // "ada"
d.get("age").asInt();            // 36
d.get("tags").size();            // 2
d.get("tags").at(1).asString();  // "y"
d.get("ok").asBool();            // true
d.get("missing").isNull();       // true
```

## The parser

`parseJson(string s) -> Json` is a free function in `Json.twl` that creates a
`JsonParser` and runs it. `JsonParser` is a small class holding `string src;
int pos; int len;` and doing recursive descent with the string utilities
(`charAt`, `substring`, `toFloat`) plus `s.length`.

Grammar handled (standard JSON):
- **whitespace** — skip space (32), tab (9), newline (10), CR (13) between
  tokens.
- **value** — dispatch on the first non-ws char: `{` object, `[` array,
  `"` string, `t` true, `f` false, `n` null, else number.
- **object** — `{` then zero or more `"key" : value` separated by `,`, then `}`;
  stored in a `Map<string, Json>`.
- **array** — `[` then zero or more values separated by `,`, then `]`; stored in
  a `List<Json>`.
- **string** — chars between `"`…`"`, building the value by concatenating
  single-char slices (`substring(src, i, i+1)`); escape sequences `\" \\ \/ \n
  \t \r \b \f` map to their literal strings (`"\n"`, etc.). (`\uXXXX` is out of
  scope for v1 — see Limitations.)
- **number** — scan a run of `-+.0-9eE`, `substring` it, `toFloat`; kind 2.
- **true/false/null** — match the keyword (advance its length), set kind.

The "single-char slice + literal escape strings" approach means **no new
compiler builtin is needed** — it's all Tawla on existing primitives.

### Errors

Any malformed input (unexpected character, unterminated string, missing `:`/`}`/
`]`, empty input) calls `panic("invalid JSON")`, which aborts with a clear
message (the existing builtin).

## Testing

`tests/test_m32.py` (via `run_twl`):
- scalars: `parseJson("42").asInt()` → 42; `parseJson("3.5").asFloat()` → 3.5;
  `parseJson("true").asBool()`; `parseJson("\"hi\"").asString()` → "hi";
  `parseJson("null").isNull()`.
- object: the example above — `get` string/int/bool, nested array `size`/`at`.
- missing key → `get(...).isNull()` is true.
- array of objects: `parseJson("[{\"n\":1},{\"n\":2}]")`, `at(0).get("n").asInt()`
  → 1, `size()` → 2.
- string escapes: `parseJson("\"a\\nb\"").asString()` contains a newline
  (length 3); `\"` and `\\` decode correctly.
- whitespace tolerance: `parseJson("  { \"a\" : 1 }  ")` works.
- malformed → non-zero exit with "invalid JSON" (e.g. `parseJson("{")`,
  `parseJson("")`).
- regression: full suite stays green.

Example: `examples/json_read.twl` parsing a small object and printing fields.

## Limitations (documented)

- `\uXXXX` unicode escapes are not decoded (v1).
- Numbers are stored as `float`; integers beyond ~2^53 lose precision.
- Duplicate object keys: last one wins (Map semantics).

## Out of scope (next milestone: JSON write)

- `jsonObject()` / `jsonArray()` builders, `setX`/`push`, `toString()`
  serialization, and `Request.respondJson`.
