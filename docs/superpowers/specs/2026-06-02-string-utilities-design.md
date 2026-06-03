# Design: string utilities (charAt / substring / toInt / toFloat / toString)

Status: approved (brainstorm) — pending implementation
Date: 2026-06-02
Milestone: M31 — additive, ships as **1.3.0** (with the JSON milestone that follows)

## Goal

Add the string building blocks needed to read and write text character by
character: index a string, slice it, and convert between strings and numbers.
These are generally useful, and they are the prerequisite for writing a JSON
parser/serializer in Tawla itself (the next milestone).

## API

Five global builtin functions (same mechanism as `sqrt`/`abs`/`panic` — no
import needed). `string.length` already exists.

- `charAt(string s, int i) -> int` — the character **code** (byte value 0–255)
  at index `i`. Returns an int so range checks read naturally
  (`c >= 48 && c <= 57` for a digit). Aborts with a `panic`-style "string index
  out of range" message if `i < 0` or `i >= s.length`.
- `substring(string s, int start, int end) -> string` — the slice `[start, end)`
  (a fresh GC-allocated string). Aborts if `start < 0`, `end > s.length`, or
  `start > end`. An empty slice (`start == end`) yields `""`.
- `toInt(string s) -> int` — parse a base-10 integer; `0` if `s` isn't numeric
  (C `atoi` semantics: leading number, else 0).
- `toFloat(string s) -> float` — parse a float; `0.0` if not numeric
  (C `strtod` semantics).
- `toString(int) -> string` / `toString(float) -> string` — number → string.
  One name, works on either argument type (type-directed in codegen, like
  `abs`). Floats use `%g` (e.g. `3.5`, matching `print`).

## Implementation

All in **codegen** — no new Python runtime, no language changes. New builtins in
sema + codegen backed by C-library functions that resolve in the JIT the same
way `printf`/`strlen`/`strcmp` already do.

- **sema.py:**
  - `charAt`, `substring`, `toInt`, `toFloat` get fixed signatures in
    `_BUILTINS`:
    - `"charAt": ([STRING, INT], INT)`
    - `"substring": ([STRING, INT, INT], STRING)`
    - `"toInt": ([STRING], INT)`
    - `"toFloat": ([STRING], FLOAT)`
  - `toString` is overloaded on its single numeric argument, so it is checked
    specially (like the math builtins): one arg that is `int` or `float` →
    returns `STRING`. Add a small `_MATH_*`-style entry or a dedicated check in
    `_check_builtin`.
- **codegen.py:**
  - Declare externs in `_declare_runtime`: `atoi(i8*) -> i32`,
    `strtod(i8*, i8**) -> double`, and `snprintf(i8*, i64, i8*, ...) -> i32`
    (var_arg). `strlen`, `memcpy` (declare `memcpy(i8*, i8*, i64) -> i8*` if not
    present), `gc_alloc` already exist.
  - `_gen_builtin` branches:
    - `charAt`: `len = strlen(s)`; bounds-check `i` against `len` (reuse the
      abort pattern: compare, branch to an error block that prints
      "string index out of range" and `exit(1)`); `gep s[i]`, `load i8`,
      `zext` to i32.
    - `substring`: bounds-check `start`/`end`; `n = end - start`;
      `buf = gc_alloc(n + 1)`; `memcpy(buf, s + start, n)`; store `0` at
      `buf[n]`; return `buf`.
    - `toInt`: `call atoi(s)`.
    - `toFloat`: `call strtod(s, null)`.
    - `toString`: if the arg is `i32`, `gc_alloc(16)` + `snprintf(buf, 16,
      "%d", n)`; if `f64`, `gc_alloc(32)` + `snprintf(buf, 32, "%g", x)`;
      return `buf`. (Format-string globals like the existing `_fmt_int`.)
  - Reuse the existing bounds-abort message global, or add a `_str_oob_msg`.

## Testing

`tests/test_m31.py` (via the `run_twl` subprocess fixture):
- `charAt`: `print(charAt("abc", 0))` → 97; `charAt("abc", 2)` → 99.
- `charAt` out of range → non-zero exit with "out of range".
- `substring`: `substring("hello", 1, 4)` → "ell"; `substring("hi", 0, 0)` → ""
  (prints empty line); full slice `substring("hi", 0, 2)` → "hi".
- `substring` out of range → abort.
- `toInt`: `toInt("42")` → 42; `toInt("xyz")` → 0; negative `toInt("-7")` → -7.
- `toFloat`: `toFloat("3.5")` → 3.5; `toFloat("nope")` → 0.
- `toString`: `toString(42)` → "42"; `toString(3.5)` → "3.5"; round-trip
  `toInt(toString(123))` → 123.
- sema errors: `charAt(5, 0)` (first arg not string); `toInt(5)` (arg not
  string); `toString("x")` (arg not numeric).
- regression: full suite stays green.

Example: extend an example or add a tiny `examples/strings_util.twl` using
`charAt`/`substring`/`toString`.

## Out of scope (the next milestone)

- The `Json` value type, JSON parser/serializer, builders, and `respondJson` —
  built on top of these utilities.
- Other string helpers (`indexOf`, `split`, `trim`, case conversion) — easy
  follow-ons if wanted.
