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

- **The basics:** `int`, `bool`, and `string`; arithmetic and comparisons;
  `if`/`else`, `while`, and functions (recursion works fine).
- **`var`:** skip the type and let it be inferred — `var x = 5;`.
- **Classes:** fields, methods, constructors, `this`, and `new`. Objects live on
  the heap.
- **Inheritance:** `class Dog : Animal { ... }`, with method overriding and
  `super(...)` to call the base constructor.
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
- `import` pulls in other files by relative path, but there's no package system
  or standard library to speak of yet.

The full design and the step-by-step history of how it was built are in
`docs/superpowers/specs/2026-05-29-tawla-language-design.md` if you're curious.

## License

MIT — see [LICENSE](LICENSE).
