# Design: JSON write (builders + toString + respondJson)

Status: approved (brainstorm) — pending implementation
Date: 2026-06-02
Milestone: M33 — additive, ships as **1.3.0** (completes the JSON arc)

## Goal

Construct `Json` values and serialize them to text, and let an HTTP handler
return JSON. Together with the read milestone this closes the
read-request-JSON / return-JSON-response loop.

## Builder + serialize API (in `Json.twl`)

Reuses the existing `Json` value type. Adds:

- Free functions: `jsonObject() -> Json` (kind 5, empty `Map`), `jsonArray() ->
  Json` (kind 4, empty `List`).
- Object mutators (instance methods on `Json`):
  `setString(string key, string v)`, `setInt(string key, int v)`,
  `setFloat(string key, float v)`, `setBool(string key, bool v)`,
  `set(string key, Json v)`.
- Array mutators: `pushString(string v)`, `pushInt(int v)`,
  `pushFloat(float v)`, `pushBool(bool v)`, `push(Json v)`.
- `toString() -> string` — serialize the tree.

```tawla
Json out = jsonObject();
out.setString("status", "ok");
out.setInt("count", 3);
Json items = jsonArray();
items.pushString("a");
items.pushString("b");
out.set("items", items);
out.toString();   // {"status":"ok","count":3,"items":["a","b"]}
```

The scalar mutators build a leaf `Json` internally (kind 1/2/3) and store it; the
object mutators require this value to be an object (`kind == 5`) and the array
mutators an array (`kind == 4`) — they assume correct use (build with
`jsonObject()`/`jsonArray()`).

### `toString()` serialization

Recursive on `kind`:
- 0 null → `null`
- 1 bool → `true` / `false`
- 2 number → `toString(this.numVal)` (so `36.0`→`36`, `3.5`→`3.5`)
- 3 string → `"` + escaped(`strVal`) + `"`
- 4 array → `[` + elements' `toString()` joined by `,` + `]`
- 5 object → `{` + (`"` + escaped(key) + `":` + value `toString()`) joined by
  `,` + `}`, iterating keys via `Map.keys()` (insertion order)

`escaped(s)` walks `s` with `charAt` and emits `\"` (34), `\\` (92), `\n` (10),
`\t` (9), `\r` (13) — built from Tawla literals (`"\\n"`, `"\\\""`, `"\\\\"`,
etc.) — and the raw single-char slice otherwise. This inverts the read-side
unescaping (round-trips for the supported set).

## `Map.keys()` in `Collections.twl`

Add `public List<K> keys()` to `Map`: returns a fresh `List<K>` containing the
keys in insertion order (copy the internal key list into a new `List`). Needed by
object serialization; broadly useful for iterating maps.

## HTTP content-type plumbing

`__http_respond` currently hardcodes `text/plain`. Add a content-type argument:

- **http_runtime.py:** `respond(rid, status, content_type, body)` — use
  `content_type` for the `Content-Type` header; the `_c_respond` CFUNCTYPE gains
  a `c_char_p` and the lambda decodes it.
- **sema.py:** `"__http_respond": ([INT, INT, STRING, STRING], VOID)`.
- **codegen.py:** declare `__http_respond` as `(i32, i32, i8*, i8*) -> void`;
  `_gen_builtin` passes the four args.
- **Http.twl:** `Request.respond(int status, string body)` →
  `__http_respond(this.id, status, "text/plain", body)`; new
  `Request.respondJson(int status, string body)` →
  `__http_respond(this.id, status, "application/json", body)`.
- **Migration:** `tests/test_m30.py`'s raw-primitive test calls
  `__http_respond(r, 200, __http_path(r))` (3 args) — update to
  `__http_respond(r, 200, "text/plain", __http_path(r))`.

## Testing

`tests/test_m33.py`:
- build + serialize: object with string/int/bool fields → exact `toString()`;
  array of scalars; nested object-in-array.
- round-trip: `parseJson(out.toString())` reads back the same values
  (`get(...).asInt()` etc.).
- escaping: a string field containing a `"` and a newline serializes with
  `\"`/`\n`, and `parseJson` of that decodes back to the original.
- `Map.keys()`: put three keys, `keys().size()` is 3 and the values match.
- `respondJson`: a server subprocess that `respondJson`s; the `http.client`
  response has `Content-Type: application/json` and the JSON body.
- `respond` still sends `text/plain` (header check).
- regression: full suite green (incl. the migrated `test_m30` raw call).

Example: `examples/json_write.twl` building an object and printing
`toString()`; optionally an API example combining `parseJson` + `respondJson`.

## Limitations (documented)

- Mutators assume correct kind (call `setX` on an object built with
  `jsonObject()`); no runtime kind guard on the builders (YAGNI).
- Numbers serialize via `toString(float)` (`%g`) — same precision caveat as the
  read side.
- Escaping covers `" \ \n \t \r` (matching the read side; no `\b`/`\f`/`\u`).

## Out of scope (next milestone)

- `fetch` (outbound HTTP client).
