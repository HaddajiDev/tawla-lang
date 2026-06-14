# Real REST Routing — Design

## Goal

Make Tawla's HTTP server usable for real REST APIs by adding the three things the
current `Router` lacks: **path parameters** (`/users/:id`), **query-string
parameters**, and **request-header** access.

## Today's limitations

- `__http_path` returns the raw request-target including the query string
  (e.g. `/users/5?q=x`).
- The `Router` matches routes with exact string equality
  (`r.path == req.path()`), so any query string breaks matching and there is no
  way to capture a path segment.
- Request headers are parsed by the runtime only to find `Content-Length`; they
  are not stored or exposed.

## API (Tawla, `Http.twl`)

`Request` gains three accessors, each returning the value or **`null`** when
absent:

- `req.param(name)` — a captured path parameter (`:name` segment).
- `req.query(name)` — a query-string value.
- `req.header(name)` — a request header, looked up case-insensitively.

`req.path()` now returns the path **without** the query string. `req.method()`,
`req.body()`, `req.respond(...)`, `req.respondJson(...)` are unchanged.

Routes are registered as before, now with `:name` segments allowed:

```tawla
router.get("/users/:id", new GetUser());
router.post("/users/:id/posts", new AddPost());
// inside a handler:
string id = req.param("id");          // "42" for GET /users/42
string page = req.query("page");      // "2"  for ?page=2, else null
string auth = req.header("Authorization");  // case-insensitive, else null
```

## Matching rules (Router)

A route matches a request when **all** hold:

1. The HTTP method matches (as today).
2. The pattern and the request path have the **same number of segments**
   (a segment is the text between `/`; leading slash ignored).
3. Each pattern segment matches its path segment:
   - a `:name` segment matches any **non-empty** path segment and captures it as
     `name`;
   - any other (static) segment must be **string-equal** to the path segment.

On a match, the captured params are bound onto the `Request` and the handler
runs. No route matches → `404 not found` (unchanged). No wildcards, no optional
segments, no regex.

## Where the work lives

### Runtime — `tawla/http_runtime.py`

- In `accept()`, split the request-target into a **clean path** and the raw
  query string; URL-decode and parse the query into a dict
  (`urllib.parse.parse_qs`, taking the first value per key); store all headers in
  a dict with **lower-cased keys**.
- `__http_path` (existing) returns the clean path (no query). Existing callers
  using query-free paths are unaffected.
- New `__http_query(rid, key)` → first value for `key`, or a **null pointer (0)**
  if absent.
- New `__http_header(rid, key)` → header value for the lower-cased `key`, or
  **null pointer (0)** if absent.
- Returning 0 (a null `char*`) makes the Tawla side see `null`; returning an
  allocated string otherwise (same `_alloc_str` path the other accessors use).

### Tawla — `tawla/stdlib/Http.twl`

- `Request` gains a private `Map<string, string> params`, initialized empty in
  the constructor. `param(name)` returns `this.params.get(name)` (the existing
  `Map.get` returns `null` for a missing key). `query(name)` returns
  `__http_query(this.id, name)`; `header(name)` returns
  `__http_header(this.id, name)`. A package-private method `bindParam(k, v)` (or
  the Router setting `params` directly) lets the Router fill it.
- The `Router` gains:
  - `splitPath(p) -> List<string>` — a pure-Tawla helper that splits a path on
    `/` using `length(p)`/`charAt(p, i)`/`substring(p, a, b)`, skipping empty
    segments (so a leading `/` and trailing `/` don't create empty parts).
  - `tryMatch(pattern, path, req) -> bool` — splits both, checks equal segment
    count, walks segments binding `:name` params onto `req` and comparing static
    segments; returns whether it matched. (Builds params into a temporary
    `Map`/the request only on a confirmed full match.)
  - `handle(req)` iterates routes; for each whose method matches, calls
    `tryMatch`; on the first match, calls the handler and returns; otherwise
    `req.respond(404, "not found")`.

`__http_query` and `__http_header` are declared to sema/codegen as string-typed
builtins (the same way `__http_method`/`__http_path`/`__http_body` already are).

## Char codes used by `splitPath`/matching

`charAt` returns a character code (int): `/` is 47, `:` is 58. `splitPath` cuts
on 47; a pattern segment is a param when its first char code is 58.

## Testing (`tests/test_m37.py`)

End-to-end via the existing HTTP test harness pattern (start the Tawla server in
a subprocess / use the in-process request path the current HTTP tests use):

- single path param: `GET /users/42` on `/users/:id` → handler sees
  `param("id") == "42"`.
- multi param: `/users/:uid/posts/:pid`.
- static + param mix and a literal-segment mismatch → 404.
- segment-count mismatch (`/users/42/x` vs `/users/:id`) → 404.
- method mismatch → 404.
- query present (`?page=2&q=hi`) → `query("page") == "2"`, `query("q") == "hi"`;
  absent key → `null`.
- header present (case-insensitive: send `Authorization`, read `authorization`)
  → value; absent → `null`.
- `path()` excludes the query string.
- regression: an existing exact route with no params still works.

(If the current HTTP tests drive the server over a real socket, reuse that
harness; otherwise add the smallest socket-based test that issues the requests.)

## Wrap-up

- Example `examples/rest_api.twl`: a small API with `/users/:id`, a query param,
  and a header read, responding with JSON.
- README: extend the HTTP bullet to mention path params, query, and headers.
- Docs site: extend the HTTP section with a path-param/query/header example.
- Version bump to **1.6.0**.

## Out of scope

- Wildcard (`*`) / optional segments / regex routes.
- Typed query helpers (`queryInt`, `queryFloat`).
- Middleware / filters.
- Response headers beyond the existing content-type handling.
- Concurrency (separate effort).
