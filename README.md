# Tawla

Tawla is a small programming language with its own compiler, `tawlac`, built
from scratch. It looks a lot like C#: you write classes with fields and methods,
you get inheritance and interfaces, and everything is statically typed. Under the
hood `tawlac` turns your code into real machine code using LLVM and runs it on
the spot, so there's no separate "compile then run" dance.

It started as a learning project to understand how compilers actually work, and
it grew into a genuinely usable little language. Source files end in `.twl`.

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
- **`for` loops:** the C-style `for (int i = 0; i < n; i = i + 1) { ... }`, with
  the loop variable scoped to the loop.
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
- **Strings:** literals with escapes, `s.length`, `==`, and `+` to join them.
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
- **`panic(s)`:** print a message and abort, for unrecoverable errors.
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
