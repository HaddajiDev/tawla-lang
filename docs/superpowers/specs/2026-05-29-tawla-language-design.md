# Tawla Language — Design Spec

**Date:** 2026-05-29
**Status:** M0–M3 complete. M3: booleans/comparisons (`i1`), `if`/`else`/`else if`,
`while`, reassignment, blocks — built on LLVM basic blocks + branches. `main` uses a
dedicated `entry` block for allocas branching to a `body` block (avoids two-builder
insertion conflicts and keeps allocas out of loops). sum 1..10 → 55. Next: M4
(functions). Output tests run the CLI as a subprocess (Windows C-runtime fd tables
prevent in-process capture of JIT'd printf).

**M4 complete.** Functions: declarations, params, `return`, calls, per-function
scopes (fresh symbol table; params become local allocas). Two-pass codegen (declare
all signatures, then bodies) enables recursion. Top level stays script-style:
function decls + leftover statements form `main`. Recursive `factorial(5)` → 120.

**M5 complete.** New `sema.py` stage between parse and codegen: types `int`/`bool`,
rejects type errors early (`int x = true;`, non-bool conditions, bad arg/return
types, mismatched `==`), `var` local inference, two-pass for recursion. `bool` is now
first-class (declarable; functions can take/return it). Name/type/arity errors now
raise `SemaError` (codegen retains them only as internal invariants). Codegen reads
types from sema-validated nodes (typed signatures, typed allocas).

**M6 (classes pt.1) — language core complete.** Classes → LLVM identified structs;
objects are heap-allocated (`malloc`) pointers. Fields, methods (mangled `Class.method`),
`this` (implicit 1st arg), single constructor (void, mangled `Class.Class`), `new`,
field read/write via GEP, method dispatch. Class types join the type system (vars,
params, returns, fields). Added `ExprStmt` (method-call statements) and `Assign` now
targets an lvalue. Data layout stamped on the module so struct sizeof is correct.
`Point.sum()` → 7.

**M6 scaffolding (Cargo-style) — done.** `project.py` + CLI: `tawlac new <name>`,
`tawlac init`, and `tawlac run` with no file = project mode (finds `Tawla.toml` by
walking up, reads `[build] entry`, runs it). Manifest read with stdlib `tomllib`.
Entry-point gap resolved by **Option 1**: the generated `src/main.twl` is a class +
top-level entry that compiles today (no fake `static void main`); a faithful C#-style
`Main` entry waits on `void` + strings + a static convention. Comments (`//`) not yet
supported. Objects are never freed (GC is a later milestone).

**M7 (inheritance) complete.** `class Dog : Animal`. Struct layout = base fields prefix
+ own (so a `Dog*` is layout-compatible with `Animal*`). Methods inherit; overrides must
match signature. `is_subtype` allows a subclass where a base is expected (var-init, assign,
args, return); codegen `_coerce` inserts pointer bitcasts. **Static dispatch**: a call uses
the variable's declared type (`Animal a = new Dog(); a.speak()` → Animal's) — M8 vtables make
it dynamic. Method resolution climbs the parent chain, bitcasting `this` to the defining
class. Constructors are not inherited; no `super` yet (subclasses set inherited fields via
`this.field`).

**M8 (polymorphism / vtables) complete.** All methods are virtual (Java-style). Every
object has a hidden vtable pointer at struct field 0 (user fields shifted to index 1+).
Each class has a constant vtable global (`[N x i8*]`) — base method slots kept in order,
overrides replace the pointer, new methods append. `new` installs the vtable; a method
call loads vtable→slot→fn-ptr and calls it, so dispatch is on the **runtime** type:
`Animal a = new Dog(); a.speak()` → 1. Fixed a latent bug: each module now uses its own
`ir.Context()` so identified struct types don't collide across compiles in one process.

**M9a (interfaces) complete.** `interface I { sig; }`; `class C : Base, IFoo, IBar`. An
interface value is a **fat pointer** `{i8* object, i8** itable}` (Go/Rust-style) — chosen
because it's the only representation that correctly handles a class implementing multiple
*unrelated* interfaces. Per-(class, interface) **itable** globals hold the class's impls in
interface-method order. `_coerce` builds the fat pointer at class→interface boundaries
(var-init/assign/arg/return/field); interface calls dispatch through the itable. Sema:
interface registry, base classification (one parent class + N interfaces), implementation
verification (all methods, matching sigs), `is_subtype` includes implemented interfaces,
`new` on an interface rejected.

**M9b (abstract) complete.** `abstract class` (cannot be `new`'d) and `abstract int m();`
(signature only). Sema: abstract methods only in abstract classes; a concrete subclass must
implement all inherited abstract methods (tracked via `ClassInfo.abstract_methods`); `new` on
an abstract class rejected. Codegen: abstract methods get no function and no body; abstract
classes get no vtable/itable global (never instantiated), but their method *tables* (slot
index + signature) are still computed so an abstract-base-typed variable dispatches correctly
through the concrete object's vtable.

**🎉 M0–M9 (the full original roadmap) complete.** Tawla is a statically-typed, natively
JIT-compiled language with arithmetic, control flow, functions, a type system + inference,
classes with single inheritance, virtual dispatch (vtables), interfaces (fat pointers +
itables), abstract classes/methods, and a Cargo-style `tawlac` toolchain. 122 tests pass.
Post-M9 arc ("do all"): M10 strings → M11 void + static Main + scaffold → M12 super →
M13 arrays → M14 review.

**M10 (strings) complete.** `string` type = NUL-terminated C string (`i8*`). String literals
(`"..."`) with escapes (`\n \t \r \" \\ \0`) become internal global byte arrays. `print`
selects `%s` vs `%d` by the value's LLVM type. Strings work as vars/params/returns/fields.
Deferred: concatenation, comparison, length.

**M11 (void + Main entry + scaffold) complete.** `void` return type (methods/functions);
`return;` (bare) allowed in void/ctor; sema rejects void in value positions and void-valued
expressions. **Default constructors**: a class with no `ctor` can be `new`'d with no args.
**Entry convention**: with no top-level statements, `tawlac run` runs `new Main().main()`.
`tawlac init` now generates the real C# `class Main { void main() { print("Hello, Tawla!"); } }`.
The original day-one goal (Cargo-style scaffold of a C# Main class) is now met.

**M12 (super) complete.** `super(args);` in a subclass constructor calls the base-class
constructor (bitcasting `this` to the base type). Sema: only inside a constructor, requires a
base class, args must match the base ctor (or default = no args). No ordering enforced.

**M13 (arrays) complete.** 1-D arrays of any element type (`int[]`, `string[]`, `Point[]`,
nested `int[][]`). Heap layout `{ i32 length, elem[] }`; `new T[n]` allocates + zero-inits
(`memset`); `a[i]` read/write via GEP; `a.length` (read-only). Type grammar parses `[]`
suffixes; declaration parsing restructured (parse `type name`, then branch func vs var) to
handle array types. No bounds checking yet. `new int[5]` filled 0..4 squared sums to 30.

**M14 (review/cleanup) complete.** `pyflakes` clean across `tawla/` + `tests/`. All 15
examples verified; edge-case combos (polymorphic interface arrays, object-returning method
chains) confirmed. Added top-level `README.md`. 157 tests pass, ~2400 LOC. Open cleanup
item: `experiments/m0_skeleton.py` is stale scratch (uses the removed `llvm.initialize()`) —
left in place since it was user-authored. `codegen.py` (~550 LOC) is the largest file; a
candidate for splitting later but cohesive as one CodeGen class.

Final feature arc ("tackle all"): M15 comments → M16 bounds → M17 string ops → M18 generics → M19 GC.

**M15 (comments) complete.** `//` line comments in the lexer (single `/` is still division).
Removed stale `experiments/m0_skeleton.py`.

**M16 (array bounds checks) complete.** Every `a[i]` (read/write) runtime-checks `0 <= i <
length`; out-of-bounds prints "array index out of bounds" and `exit(1)`.

**M17 (string operations) complete.** `s.length` (via `strlen`), `==`/`!=` (via `strcmp`),
and `+` concatenation (malloc + `strcpy`/`strcat`). `.length` is read-only.

**M18 (generics) complete.** Generic classes `class Box<T> { ... }` via **monomorphization**
in a new `monomorphize.py` pass that runs after parse, before sema: it finds every
instantiation (`Box<int>`, `Pair<int,string>`), stamps out a concrete class (`Box$int`) with
the type params substituted, and rewrites all `Box<int>` type references to the mangled name.
After this pass the compiler sees only ordinary classes. Supports multiple type params and
class-typed args. Limits (first cut): generic classes only (no generic free functions/methods),
no nested generic args (`Box<Box<int>>`).

**M19 (garbage collection) complete.** A Python-hosted GC heap (`gc_runtime.py`): all heap
allocations (objects, arrays, concatenated strings) go through `gc_alloc`, which tracks each
block. `collect()` runs a **conservative mark-sweep** — roots come *precisely* from a shadow
stack of local pointer/interface slots (codegen pushes them on declaration, restores the stack
depth before every return), while object interiors are scanned *conservatively* (any word
matching a live block address is a pointer), which is memory-safe (never frees something
reachable). Runtime functions are injected as JIT symbols via `llvm.add_symbol`. Builtins:
`collect()` and `__live()` (live block count, for tests). Collection is **explicit** (not
alloc-triggered) so an un-rooted expression temporary can't be freed mid-evaluation. Verified:
garbage reclaimed, rooted objects survive and stay valid, field-reachable objects survive, and
a `collect()`-every-iteration loop computes the right result. Cycles are reclaimed (mark-sweep,
unlike refcounting).

**🏁 Everything on the roadmap and the entire "beyond M9" list is done** (M0–M19): a
statically-typed, natively JIT-compiled, C#-style OOP language with classes, inheritance,
virtual dispatch, interfaces, abstract types, generics, strings, arrays (bounds-checked),
comments, a Cargo-style toolchain, and a garbage collector. 190 tests, ~2900 LOC, 18 examples.

## Vision

Tawla is a statically-typed, natively-compiled programming language with C-like
flavor and Java/C#-style classes. The goal is a working language + `tawlac`
compiler, built incrementally so every milestone runs.

**Working agreement (updated 2026-05-30):** Claude writes the implementation code
across the project; the user reviews and directs. (This reverses the original
"user writes all code by hand to learn" agreement.) Claude still explains what it
builds and why, so the user can review effectively.

## Key decisions

| Decision | Choice |
|---|---|
| Backend | LLVM (real native machine code) |
| Compiler host language | Python 3 + `llvmlite` |
| Type system | Static typing; explicit (`int x = 5;`) required, `var` inference optional (local-only, type-of-initializer) |
| OOP goal | Fields + methods → inheritance → polymorphism (vtables) → interfaces/abstract |
| Keywords | Defined as we go; placeholder C-like defaults, renamed freely (lexer lookup table) |
| Build strategy | Vertical slices ("walking skeleton") — tiny end-to-end compiler first, add one feature at a time through all stages |
| Compiler CLI | `tawlac` with subcommands: `tawlac run file.twl` (now), `tawlac build file.twl` (native binary, later). |
| Output mode | **JIT run-style is the inner dev loop** through all milestones: `tawlac run` compiles to native code via llvmlite JIT and runs instantly in memory. Cross-platform by construction (JITs for the host machine). Toolchain = just `pip install llvmlite`. |
| Native binary emission | `tawlac build` emits a native binary + links locally. Deferred until development moves to **Linux/WSL**, where it produces a native **ELF** (host==target, so **not** cross-compilation). Targeted ~M2 *once on Linux*; stays JIT-only while on Windows. |
| Dev vs target platform | Developing on **Windows now**; **Linux is the real target**. On Windows, JIT runs Windows code in-memory (fine for testing). Emitting a *Linux* binary from Windows would be cross-compilation, so native-binary work waits for the Linux/WSL move. |
| Cross-compilation | True host≠target cross-compilation (e.g. Linux→Windows `.exe`) is an **optional far-future** topic, explicitly **not** committed now. |
| Source file extension | `.twl` (provisional) |

## Architecture (pipeline)

```
source.twl → [Lexer] → tokens → [Parser] → AST → [Sema] → typed AST → [CodeGen] → LLVM IR → [llvmlite JIT] → runs
```

| Stage | Job |
|---|---|
| Lexer | Text → tokens; home of custom keywords |
| Parser | Tokens → AST (recursive descent, operator precedence) |
| Sema | Type-check, resolve names, infer `var`, scopes (arrives M5) |
| CodeGen | Typed AST → LLVM IR via llvmlite |
| JIT | Compile IR to native code in memory and execute |

## Repo layout (target)

```
Tawla_lang/
├── tawla/
│   ├── tokens.py        # token kinds
│   ├── lexer.py         # text → tokens
│   ├── ast_nodes.py     # AST node classes
│   ├── parser.py        # tokens → AST
│   ├── sema.py          # type-check / resolve (M5+)
│   ├── codegen.py       # AST → LLVM IR
│   ├── compiler.py      # runs pipeline + JIT
│   └── cli.py           # `python -m tawla run hello.twl`
├── tests/               # pytest, one file per stage
├── examples/            # sample .twl programs
└── pyproject.toml
```

## Milestone roadmap

| # | Milestone | New concepts | Runs |
|---|---|---|---|
| M0 | Walking skeleton | Full pipeline wired; llvmlite JIT; `main` returns a constant | `42` → 42 |
| M1 | Arithmetic | Lexer, recursive-descent parser, precedence, math IR | `1 + 2 * 3` → 7 |
| M2 | Variables + print | Symbol table, `int x=...;`, call C `printf` | `int x=5; print(x*2);` → 10 |
| M3 | Control flow | Booleans, comparisons, if/else, while, basic blocks | sum 1..10 loop |
| M4 | Functions | Decls, params, returns, calls, scopes | recursive factorial |
| M5 | Type checking + `var` | Sema stage, type errors, inference | rejects `int x = true;` |
| M6 | Classes pt.1 | Fields, methods, `this`, constructors, heap alloc, name mangling | `Point.distance()` |
| M7 | Inheritance | Subclass layout, inherit/override methods | `Dog : Animal` |
| M8 | Polymorphism | vtables, dynamic dispatch | virtual `speak()` |
| M9 | Interfaces / abstract | Interface vtables, contracts | `IShape` |

Beyond M9 (later): strings, arrays, memory cleanup, generics.

## Project tooling (Cargo-style) — built at M6

Deliberately deferred until classes exist (M6), so the scaffold emits a real,
compilable C#-style `Main` class from day one rather than a placeholder.

- `tawlac new <name>` — create a new project directory (like `cargo new`).
- `tawlac init` — scaffold a project in the current directory (like `cargo init`).
- `tawlac run` (no file) — find `Tawla.toml` (walking upward), compile its entry,
  and run it. `tawlac run <file>` still works for one-off files.

Layout:
```
myproject/
├── Tawla.toml        # [package] name, version  +  [build] entry = "src/main.twl"
└── src/
    └── main.twl      # class Main { void main() { print("Hello, Tawla!"); } }
```

`Tawla.toml` is read with Python's built-in `tomllib`. Room to grow later
(dependencies, build settings, output mode).

## Working loop per milestone

Explain concept + why → Claude implements the slice → run a test program →
user reviews/directs → refine. Always runnable.
