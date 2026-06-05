# Exception Handling: `fuck_around` / `find_out` — Design

## Goal

Give Tawla try/catch. A `fuck_around { ... }` block guards code; if anything
goes wrong inside it, control jumps to the matching `find_out` block instead of
killing the process. Users can raise their own errors with `throw`, and the
built-in errors that exist today (`panic`, null-dereference, array-out-of-bounds,
bad string index) become catchable too.

The keywords are deliberately: `fuck_around` (try), `find_out` (catch),
plus `throw`.

## Today's error model (what we are changing)

Every error in Tawla currently prints a message and calls the C `exit(1)`:
- `panic("msg")` — `codegen.py` emits print + `exit`.
- null dereference, array bounds, bad string index — emitted inline in IR as a
  message print + `exit` (`codegen.py` `_bounds_check`, the string-index check,
  the null checks).

There is no exception object, no unwinding, nothing catchable. This design adds
a non-local jump from a throw site back to the nearest enclosing handler.

## Syntax

Three new keywords: `fuck_around`, `find_out`, `throw`.

```tawla
fuck_around {
    risky();
    throw "kaboom";          // throw a string message
} find_out (e) {
    print(e);                // e is a string: the message that was thrown
}

// bare form — catch but ignore the message:
fuck_around {
    mayFail();
} find_out {
    print("recovered");
}
```

`throw expr;` where `expr` has type `string`.

A `find_out` always immediately follows its `fuck_around`. Both take a brace
block (same block grammar as `if`/`while`).

## Semantics

1. **`throw expr;`** unwinds to the nearest enclosing `find_out`, carrying the
   string message. Outside any `fuck_around`, a `throw` behaves like `panic`:
   print the message and `exit(1)`.

2. **Built-in errors are catchable.** `panic(msg)`, null-dereference,
   array-out-of-bounds, and bad string index all route through the same
   unwind path. Inside a `fuck_around` they jump to the `find_out` (binding their
   existing message string). With **no** enclosing handler they behave exactly as
   today: print the message and `exit(1)`. (Backward compatible.)

3. **`find_out (e)`** binds `e` as a `string` local scoped to the catch body.
   Bare **`find_out`** catches without binding.

4. **Rethrow.** The handler is popped *before* the catch body runs, so a `throw`
   (e.g. `throw e;`) inside `find_out` propagates to the next outer handler, or
   aborts if there is none.

5. **`return`** is allowed inside both blocks. It unwinds (pops) any handlers
   installed by enclosing `fuck_around` blocks in the current function before
   returning.

6. **`break` / `continue`** may **not** cross a `fuck_around`/`find_out`
   boundary in v1 — doing so is a sema error
   ("cannot break/continue out of a fuck_around block"). A `break`/`continue`
   whose target loop is *inside* the guarded block is fine. This restriction can
   be lifted later.

7. **Nesting** works: handlers form a stack; the innermost active one catches.

8. **GC correctness.** Frames abandoned by a jump may have pushed GC roots. At
   `fuck_around` entry we capture `gc_root_depth()`; on catch we
   `gc_root_settop(savedDepth)` to release roots from the unwound frames. (These
   hooks already exist for normal scope exit.)

9. **Caught value is always a `string`.** No exception types or objects — this
   matches Tawla's existing "an error is a message" model and keeps the feature
   small.

## Mechanism: `setjmp` / `longjmp` + a handler-stack runtime

The non-local jump uses the C library's `setjmp`/`longjmp`. This is the
classic, lightweight way to do exceptions in C and fits a JIT far better than
LLVM's landingpad/personality EH (which is platform-ABI-specific and painful
under MCJIT).

### `eh_runtime.py` (new, Python-hosted like `gc_runtime`)

Holds a thread-local stack of `jmp_buf` pointers and the pending message,
registered via `llvm.add_symbol`:

- `__eh_push(buf: void*)` — push a handler's jmp_buf pointer.
- `__eh_pop()` — pop the top handler.
- `__eh_top() -> void*` — top jmp_buf pointer, or null if the stack is empty.
- `__eh_set_msg(s: char*)` — store the message for the in-flight throw.
- `__eh_msg() -> char*` — read the stored message (for the catch binding).

`setjmp` and `longjmp` themselves are the **C library** functions (not Python).
Their addresses are obtained via ctypes from the C runtime (`msvcrt`/`ucrtbase`
on Windows, libc on macOS/Linux) and bound with `llvm.add_symbol` so the JIT can
call them. The `jmp_buf` is an opaque byte buffer; codegen allocates a
generously-sized one (e.g. 256 bytes) via `alloca` in the guarded function's
frame.

### Codegen — `fuck_around`/`find_out`

```
buf      = alloca [256 x i8]            ; jmp_buf, lives in this frame
depth    = call gc_root_depth()
call __eh_push(buf)
r        = call setjmp(buf)             ; call marked "returns_twice"
if r == 0:
    <try body>
    call __eh_pop()
    br after
else:                                   ; arrived via longjmp
    call gc_root_settop(depth)          ; release roots from unwound frames
    msg = call __eh_msg()               ; bind for (e), if present
    <catch body>
    br after
after:
```

To keep `returns_twice` correct, values the catch path needs are read from
runtime calls / allocas after the `setjmp`, not carried in registers across it.

### Codegen — `throw` / `panic` / built-in traps

Replace the current "print + exit(1)" with:

```
top = call __eh_top()
if top == null:
    <print message>                     ; today's behavior
    call exit(1)
else:
    call __eh_set_msg(message)
    call longjmp(top, 1)                ; never returns here
```

All throw sites are pure IR (no Python ctypes callback sits on the stack between
a throw and its `setjmp`), so `longjmp` between JIT frames is clean.

### `return` unwinding

Codegen tracks how many handlers are currently pushed in the function at each
point. A `return` inside guarded code emits one `__eh_pop()` per still-active
handler before the `ret`. Inside a `find_out` body the block's own handler is
already popped, so only outer handlers are unwound.

## Components / files

- `tawla/tokens.py` — `KW_FUCK_AROUND`, `KW_FIND_OUT`, `KW_THROW` (keywords
  `fuck_around`, `find_out`, `throw`).
- `tawla/lexer.py` — keywords map (identifier-based, no lexer logic change beyond
  the keyword table; `fuck_around`/`find_out` are single identifiers).
- `tawla/ast_nodes.py` — `TryCatch(try_body, catch_var, catch_body)` and
  `Throw(value)` nodes.
- `tawla/parser.py` — parse `fuck_around` block + required `find_out` (optional
  `(ident)`); parse `throw expr;`. Dispatch in `statement()`.
- `tawla/sema.py` — `throw` requires a `string`; `find_out (e)` introduces `e:
  string` in the catch scope; reject `break`/`continue` crossing a `fuck_around`
  boundary.
- `tawla/monomorphize.py` — recurse through the new nodes (pass-through, like
  other statements).
- `tawla/codegen.py` — emit the handler install/catch and the throw/longjmp;
  reroute the existing panic/null/bounds/string-index `exit` sites through the
  `__eh_top()` check; track active-handler count for `return`.
- `tawla/eh_runtime.py` — new runtime (handler stack + msg + setjmp/longjmp
  binding).
- `tawla/compiler.py` — register the eh runtime symbols (alongside gc/io/etc.).
- `tawlac.spec` — add `tawla.eh_runtime` to `hiddenimports`.
- Tests `tests/test_m36.py`; example `examples/errors.twl`; README + docs;
  version bump to `1.5.0`.

## Testing

- `throw "x"` caught by `find_out (e)` → `e == "x"`.
- bare `find_out` catches and runs without binding.
- `panic("boom")` inside `fuck_around` is caught (prints `boom`, program
  continues and exits 0).
- null-dereference inside `fuck_around` is caught.
- array-out-of-bounds inside `fuck_around` is caught.
- uncaught `throw` (no handler) prints the message and exits non-zero
  (regression: behaves like panic).
- nested `fuck_around`: inner catch handles; outer is untouched.
- rethrow: `find_out (e) { throw e; }` propagates to an outer handler.
- `return` from inside a `fuck_around` body returns the right value (handler
  popped, no stack corruption on a later call).
- `return` from inside a `find_out` body works.
- sema error: `break;`/`continue;` that crosses a `fuck_around` boundary is
  rejected.
- GC: allocate objects inside a caught `fuck_around`, then `collect()` and check
  `__live()` is sane (roots from the unwound frame were released).

## Risks

- **`setjmp`/`longjmp` under MCJIT is the central risk**, especially on Windows
  (CRT setjmp / SEH interactions) and getting `returns_twice` codegen right.
  **The implementation plan's first task is a feasibility spike**: prove a
  setjmp→longjmp round-trip works in our llvmlite JIT before building any of the
  language layer. If the spike fails, stop and reconsider the mechanism.
- `jmp_buf` size is platform-dependent; we over-allocate (256 bytes) to be safe.
- The three OS binaries must each be re-verified (the CI smoke tests cover
  build + a basic run; a thrown-and-caught example can be added to the smoke set
  if desired).

## Out of scope

- `finally` / always-runs block.
- Exception types or objects (catch is always a `string`).
- Catching across `break`/`continue`.
- Multiple typed `find_out` clauses.
