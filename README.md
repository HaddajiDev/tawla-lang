# Tawla

Tawla is a small programming language with its own compiler, `tawlac`, built
from scratch. It looks a lot like C#: you write classes with fields and methods,
you get inheritance and interfaces, and everything is statically typed. Under the
hood `tawlac` turns your code into real machine code using LLVM and runs it on
the spot, so there's no separate "compile then run" dance.

It started as a learning project to understand how compilers actually work, and
it grew into a genuinely usable little language. Source files end in `.twl`.

**Documentation:** https://haddajidev.github.io/tawla-lang-docs/

Here's the whole "hello world":

```tawla
class Main {
    void main() {
        print("Hello, Tawla!");
    }
}
```

```
$ tawlac run hello.twl
Hello, Tawla!
```

## Getting it running

You need Python 3.11 or newer. Install it from PyPI with pip:

```
pip install tawla
```

That pulls in everything it needs (including LLVM, via llvmlite) and gives you the
`tawlac` command. Works the same on Windows, macOS, and Linux.

### No Python? Download a standalone binary

Each release also ships a self-contained `tawlac` that bundles everything it
needs — no Python install required. Grab the one for your OS from the
[Releases page](https://github.com/HaddajiDev/tawla-lang/releases) and put it on
your `PATH`:

- **Windows:** download `tawlac-windows.exe`, rename it to `tawlac.exe`, move it
  into a folder such as `C:\tools\tawla`, then add that folder to your `Path`
  environment variable (Settings → "Edit the system environment variables" →
  Environment Variables → edit `Path`). Open a new terminal and run `tawlac`.
- **macOS:** download `tawlac-macos`, then:
  ```
  mv tawlac-macos tawlac
  chmod +x tawlac
  sudo mv tawlac /usr/local/bin/
  ```
  First launch may be blocked because the binary is unsigned — allow it under
  System Settings → Privacy & Security, or run
  `xattr -d com.apple.quarantine /usr/local/bin/tawlac`.
- **Linux:** download `tawlac-linux`, then:
  ```
  mv tawlac-linux tawlac
  chmod +x tawlac
  sudo mv tawlac /usr/local/bin/
  ```

Then `tawlac run app.twl` works from anywhere, exactly like the pip version.

Hacking on it from a clone of this repo instead? That works too:

```
pip install llvmlite
python -m tawla run examples/hello.twl
```

Either way you get the `tawlac` command (or `python -m tawla`) with a few
subcommands:

```
tawlac run app.twl     # compile and run a file
tawlac new myapp       # scaffold a new project (like cargo new)
tawlac init            # scaffold one in the current folder
tawlac run             # run the current project (reads Tawla.toml)
tawlac version         # what version is this
tawlac help            # or: tawlac help run
```

## What the language can do

- **The basics:** `int`, `float`/`double`, `bool`, and `string`; arithmetic and
  comparisons; `if`/`else`, `while`, `for`, and functions (recursion works fine).
- **Numbers:** integer math with `int`, and 64-bit floating point with `float`
  (or `double` — same thing). Ints widen to floats automatically when you mix
  them, so `7.0 / 2` is `3.5` while `7 / 2` stays `3`.
- **`for` loops:** the C-style `for (int i = 0; i < n; i++) { ... }`, with
  the loop variable scoped to the loop.
- **Increment/decrement:** `i++`, `++i`, `i--`, `--i` as shorthand for
  `i = i + 1` / `i = i - 1` (statement form — works on variables, fields, and
  array elements).
- **Logical operators:** `&&`, `||`, and `!` on bools, with short-circuit
  evaluation (so `u != null && u.alive()` is safe).
- **Ternary:** `cond ? a : b` picks a value inline (lazy — only the taken
  branch runs).
- **`var`:** skip the type and let it be inferred — `var x = 5;`.
- **`null` & defaults:** reference types (objects, strings, arrays) can be
  `null`, and a declaration can skip the initializer — `int x;` is `0`,
  `bool b;` is `false`, `User u;` is `null`. Using a `null` (calling a method,
  reading a field, indexing) gives a clean "null reference" error instead of a
  crash. Value types (`int`, `float`, `bool`) can't be null.
- **Classes:** fields, methods, constructors, `this`, and `new`. Objects live on
  the heap.
- **Inheritance:** `class Dog : Animal { ... }`, with method overriding and
  `super(...)` to call the base constructor.
- **Encapsulation:** members are `private` by default; mark them `public` to
  expose them or `protected` to share with subclasses. Constructors are `public`
  by default. Access is checked at compile time. (Heads up: code written for
  Tawla 0.x needs `public` added to anything used across class boundaries.)
- **Polymorphism:** methods are virtual, so the right one gets picked at runtime
  based on the actual object type (this is done with vtables).
- **Interfaces:** `interface Shape { int area(); }`, and any class can implement
  it, even classes that share no common parent.
- **Abstract classes:** mark a class `abstract` and leave some methods without a
  body for subclasses to fill in.
- **Generics:** `class Box<T> { ... }`, used as `Box<int>` or `Box<string>`.
- **Strings:** literals with escapes, `s.length`, `==`, and `+` to join them,
  plus `charAt(s, i)` (character code), `substring(s, a, b)`, `toInt(s)` /
  `toFloat(s)`, and `toString(n)` (number to string).
- **Arrays:** `new int[n]`, indexing with `a[i]` (bounds-checked, so you get a
  clear error instead of a crash), and `a.length`.
- **Comments:** `// like this`.
- **Imports:** split code across files with `import "other.twl";` — the path is
  relative to the file importing it, and the `.twl` is optional.
- **IO library:** `import "IO.twl";` (a small module that ships with the
  compiler) gives you `readLine()`, `readInt()`, `readFloat()`, and `write(s)`
  (print with no trailing newline) for reading input and prompting.
- **Collections:** `import "Collections.twl";` gives you a growable `List<T>`
  (`add`, `get`, `set`, `size`) and a `Map<K,V>` (`put`, `get`, `has`, `size`).
  `Map.get` returns `null` for a missing object value. (No nested generics yet,
  e.g. `Map<string, List<int>>`.)
- **JSON:** `import "Json.twl";` then `parseJson(text)` returns a `Json` value
  you navigate with `get`/`at`/`size` and read with
  `asInt`/`asFloat`/`asBool`/`asString` (plus `isNull`/`isArray`/... checks).
  Build with `jsonObject()`/`jsonArray()` + `setString`/`setInt`/`set`/`push…`
  and `toString()`; in a handler, `req.respondJson(200, out.toString())` sends
  `application/json`. The whole parser/serializer is written in Tawla itself.
- **`panic(s)`:** print a message and abort, for unrecoverable errors.
- **Exceptions:** `fuck_around { ... } find_out (e) { ... }` is try/catch — `e`
  is the error message string. `throw "msg";` raises one, and built-in errors
  (`panic`, null dereference, array-out-of-bounds) are catchable too. Use bare
  `find_out { ... }` to ignore the message.
- **HTTP server:** `import "Http.twl";` gives you a `Server`, a `Request`, and an
  Express-style `Router` with `Handler` classes. Routes take path params —
  `router.get("/users/:id", new GetUser())` — and inside a handler `req.param("id")`,
  `req.query("page")`, and `req.header("Authorization")` read the path param,
  query string, and request header (each `null` when absent). `req.method()`/
  `path()`/`body()`/`respond()`/`respondJson()` round it out. Single-threaded,
  minimal HTTP/1.1.
- **HTTP client (`fetch`):** `fetch(url)` (GET) or `httpRequest(method, url, body)`
  returns a `Response` with `status()` and `body()` — call other services.
  Network failures come back as `status() == 0`.
- **SQLite:** `import "Sql.twl";` gives you `Db`, prepared `Stmt`s, and a `Rows`
  cursor — `Db db = new Db("app.db"); Stmt q = db.prepare("SELECT name FROM users WHERE age > ?"); q.bindInt(0, 18); Rows r = q.query();`
  then `r.next()` / `r.getString("name")`. Parameters bind by index
  (injection-safe); SQL errors throw (catch with `fuck_around`/`find_out`).
- **Backend essentials:** `import "Sys.twl";` (`getenv`, `now`/`nowMillis`/`sleepMillis`,
  `uuid`), `import "Fs.twl";` (`readFile`/`writeFile`/`appendFile` — throwing —
  and `exists`), and `import "Crypto.twl";` (`sha256`, `hmacSha256`). The basics
  for config, logging, IDs, and signing.
- **Built-in functions:** a handful of predefined functions you can call without
  declaring anything — `sqrt`, `pow`, `abs`, `min`, `max`, `floor`, `ceil` for
  math, plus `collect()`/`__live()` for the GC.
- **Garbage collection:** you don't free memory by hand. Call `collect()` when
  you want a cleanup pass; `__live()` tells you how many objects are still around.

There's a runnable example for pretty much every feature in `examples/` — poke
around in there to see how things look in practice.

## How it works, roughly

`tawlac` runs your code through the usual compiler stages:

```
source.twl -> lexer -> parser -> sema -> codegen -> LLVM -> JIT -> runs
```

- the **lexer** chops the text into tokens
- the **parser** builds a tree out of those tokens
- **sema** checks the types and catches mistakes before any code is generated
- **codegen** turns the checked tree into LLVM instructions
- LLVM compiles that to machine code and the **JIT** runs it immediately

Each piece lives in its own file under `tawla/`, so it's not hard to follow if
you want to read along.

## Running the tests

```
./venv/Scripts/python -m pytest
```

There are around 200 tests. Programs that print output are checked by running
`tawlac` as a separate process and looking at what it prints (this sidesteps a
Windows quirk where output from JIT-compiled code is hard to capture in-process).

## What's not done yet

It's a real language, but it's still a young one. A few honest gaps:

- `tawlac build` (making a standalone `.exe` *from your Tawla program*) isn't
  done — for now everything runs through `tawlac run`.
- Generics only cover classes, not standalone functions, and you can't nest them
  like `Box<Box<int>>`.
- Garbage collection has to be triggered with `collect()`; it doesn't kick in on
  its own yet.

The full design and the step-by-step history of how it was built are in
`docs/superpowers/specs/2026-05-29-tawla-language-design.md` if you're curious.

## License

MIT — see [LICENSE](LICENSE).
