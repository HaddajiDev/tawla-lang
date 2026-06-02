# Design: collections (List<T> and Map<K,V>)

Status: approved (brainstorm) — pending implementation
Date: 2026-06-01
Milestone: M27 — additive, ships as **1.1.0**

## Goal

Give Tawla growable collections — a `List<T>` and a key/value `Map<K,V>` — as a
bundled standard-library module, plus a `panic(string)` builtin for unrecoverable
errors. This is the data-structure layer backends need (params, headers, JSON-ish
objects).

## Surface (what programs write)

Import the module like `IO.twl`:

```tawla
import "Collections.twl";

List<int> xs = new List<int>();
xs.add(10); xs.add(20);
xs.size();         // 2
xs.get(0);         // 10
xs.set(0, 99);

Map<string, int> ages = new Map<string, int>();
ages.put("ada", 36);
ages.has("ada");   // true
ages.get("ada");   // 36
ages.has("bob");   // false
```

**API:**
- `List<T>`: `add(T)`, `get(int) -> T`, `set(int, T)`, `size() -> int`
- `Map<K,V>`: `put(K, V)`, `get(K) -> V`, `has(K) -> bool`, `size() -> int`

**Behavior:**
- `List.get`/`List.set` with an index outside `[0, size())` → `panic("List.get:
  index out of range")` (clean abort, non-zero exit).
- `Map.get` on a missing key returns `null` when `V` is a reference type, else the
  zero value (`0` / `false` / `0.0`). Pair with `has(key)`. (Relies on the
  default-initialized-declaration feature: an uninitialized `V` is the type's
  default.)
- `Map` keys are compared with `==`: **string keys match by value**; object keys
  match by identity (pointer equality).

## Components

### 1. `panic(string)` builtin

- **sema:** add to `_BUILTINS`: `"panic": ([STRING], VOID)`.
- **codegen** (`_gen_builtin`): generate the argument, `printf("%s\n", msg)`
  using the existing `_fmt_str`, then `call exit(1)`; return that call. No
  `unreachable` (so a `panic(...)` statement doesn't terminate the block — any
  following code is valid-but-dead IR, never reached at runtime).

### 2. `tawla/stdlib/Collections.twl`

Pure Tawla. `List<T>` is a growable array; `Map<K,V>` is parallel arrays with a
linear scan. Internals are `private`, the API is `public` (so it also exercises
encapsulation). No `&&`/`||` are used (Tawla has none yet) — range checks are two
separate `if`s.

```tawla
class List<T> {
    private T[] items;
    private int count;

    public List() {
        this.items = new T[4];
        this.count = 0;
    }

    public int size() { return this.count; }

    public void add(T x) {
        if (this.count == this.items.length) { this.grow(); }
        this.items[this.count] = x;
        this.count = this.count + 1;
    }

    public T get(int i) {
        if (i < 0) { panic("List.get: index out of range"); }
        if (i >= this.count) { panic("List.get: index out of range"); }
        return this.items[i];
    }

    public void set(int i, T x) {
        if (i < 0) { panic("List.set: index out of range"); }
        if (i >= this.count) { panic("List.set: index out of range"); }
        this.items[i] = x;
    }

    private void grow() {
        T[] bigger = new T[this.items.length * 2];
        int i = 0;
        while (i < this.count) { bigger[i] = this.items[i]; i = i + 1; }
        this.items = bigger;
    }
}

class Map<K, V> {
    private K[] keys;
    private V[] vals;
    private int count;

    public Map() {
        this.keys = new K[4];
        this.vals = new V[4];
        this.count = 0;
    }

    public int size() { return this.count; }

    private int indexOf(K key) {
        int i = 0;
        while (i < this.count) {
            if (this.keys[i] == key) { return i; }
            i = i + 1;
        }
        return -1;
    }

    public bool has(K key) { return this.indexOf(key) >= 0; }

    public V get(K key) {
        int i = this.indexOf(key);
        if (i >= 0) { return this.vals[i]; }
        V notfound;            // default: 0 / false / null
        return notfound;
    }

    public void put(K key, V value) {
        int i = this.indexOf(key);
        if (i >= 0) { this.vals[i] = value; return; }
        if (this.count == this.keys.length) { this.grow(); }
        this.keys[this.count] = key;
        this.vals[this.count] = value;
        this.count = this.count + 1;
    }

    private void grow() {
        K[] bk = new K[this.keys.length * 2];
        V[] bv = new V[this.vals.length * 2];
        int i = 0;
        while (i < this.count) {
            bk[i] = this.keys[i]; bv[i] = this.vals[i]; i = i + 1;
        }
        this.keys = bk;
        this.vals = bv;
    }
}
```

This compiles with no codegen changes specific to collections: it relies on
generics (monomorphization stamps `List$int`, `Map$string$int`, …), arrays,
`new T[n]` with a type parameter, `==` on the concrete key type, default-init for
`V notfound;`, void early `return;`, and private-method calls via `this`.

### 3. Parser fix — generic-typed local declarations

`_is_decl_start` currently recognizes `IDENT IDENT` and `IDENT[] IDENT` but not
`List<int> xs`. Extend it: when the current token is `IDENT` and the next is `<`,
scan forward over a balanced `<...>` (tracking `<`/`>` nesting); if the token
immediately after the matching `>` is an `IDENT`, it is a declaration. Otherwise
fall through to statement parsing (so `a < b;` is unaffected — there is no closing
`>` followed by an identifier). `var xs = new List<int>()` already works and is
unchanged.

### Packaging

`tawla/stdlib/Collections.twl` ships via the existing `[tool.setuptools.package-data]`
`tawla = ["stdlib/*.twl"]` rule (same as `IO.twl`). The loader's stdlib search
path already resolves `import "Collections.twl"`.

## Testing

`tests/test_m27.py`:
- `panic` standalone: a program that calls `panic("boom")` exits non-zero and
  prints `boom` (subprocess via `run_twl`).
- List: add/get/set/size; growth beyond the initial capacity of 4 (add ~10
  items, read them back); out-of-range `get` and `set` → non-zero exit with
  "index out of range".
- Map: put/get/has/size; overwrite an existing key; missing key → `0` for
  `Map<string,int>` and `null` for `Map<string,SomeClass>` (checked via `==
  null`); `has` true and false.
- parser: `List<int> xs = new List<int>(); xs.add(1); print(xs.get(0));` runs.
- compile/run end to end through `import "Collections.twl"`.
- regression: full suite stays green.

Example: `examples/collections.twl` exercising a `List<int>` and a
`Map<string,int>`.

## Limitations (documented)

- **No nested generics** — `Map<string, List<int>>` / `List<List<int>>` are not
  supported (monomorphization is single-level; pre-existing limitation).
- `Map` is O(n) per operation (linear scan) — fine for small maps; the API allows
  swapping in a hash-based implementation later without changing call sites.
- Object/`Map` keys compare by identity, not value (only `string`/`int`/etc. keys
  match by value).

## Out of scope

- List `contains`/`removeAt`, Map `remove`/`keys` (easy follow-ons).
- A hash-based `Map`.
- Literal syntax (`[1,2,3]` / `{"a":1}`).
