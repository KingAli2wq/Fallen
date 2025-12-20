# Fallen Language — instruction.md (Complete Reference)

# Fallen Language — Instruction Guide

This document is the up-to-date guide for everything Fallen supports right now.

## Quick start

Create a file `hello.fallen`:

```fallen
write("Hello, Fallen!")
```

Run it:

```bash
python cli.py run hello.fallen
```

## CLI

```bash
python cli.py parse <file.fallen>   # print AST
python cli.py build <file.fallen>   # print constants + bytecode
python cli.py run <file.fallen>     # run on the VM

# Interactive mode
python cli.py repl                  # start a REPL (keeps state between lines)

# Show Python traceback (debug the interpreter itself)
python cli.py run <file.fallen> --debug
python cli.py repl --debug
```

## Syntax basics

- Programs run top-to-bottom.
- Blocks use braces `{ ... }`.
- `#` starts a comment.

```fallen
# comment
if true {
    write("ok")
}
```

## Types and assignment

Typed assignment markers:

- `=s` string
- `=i` int
- `=f` float
- `=b` bool
- `=l` list
- `=d` dict

```fallen
name =s "Ali"
age  =i 17
pi   =f 3.14
ok   =b true

nums =l [1, 2, 3]
cfg  =d {"mode": "dev"}
```

## Literals

```fallen
"text"      # string
123         # int
3.14        # float
true        # bool
false       # bool

[1, 2, 3]                 # list
{"a": 1, "b": 2}         # dict (keys must be strings)
```

## Operators

### Math

`+  -  *  /`

```fallen
x =i 5 + 3
y =i x * 2
```

### Comparisons

`==  !=  <  <=  >  >=`

```fallen
if score >= 50 {
    write("Pass")
}
```

### Boolean logic (short-circuit)

- `and` (short-circuits)
- `or` (short-circuits)
- `not`

```fallen
if (role == "admin" or role == "mod") and not banned {
    write("welcome")
}
```

Important: `if`/`while` conditions must be boolean.

## Control flow

### if / elif / else

```fallen
if x == 1 {
    write("one")
} elif x == 2 {
    write("two")
} else {
    write("other")
}
```

### while

```fallen
i =i 0
while i < 3 {
    write(i)
    i =i i + 1
}
```

### for

```fallen
nums =l [10, 20, 30]
for n in nums {
    write(n)
}
```

### stop / continue

- `stop` exits the nearest loop.
- `continue` skips to the next iteration.

## Functions

```fallen
func add(a =i, b =i) {
    return a + b
}

write(add(2, 3))
```

Notes:

- Recursion is supported.
- Reaching the end of a function returns `None`.

## Built-in functions

### write(x)

Print one value.

```fallen
write("hi")
```

### enter(prompt)

Reads user input (returns a string).

```fallen
name =s enter("Name: ")
write(name)
```

### Conversions

- `conv_int(x)`, `conv_float(x)`, `conv_bool(x)` convert or raise a runtime error.
- `try_conv_int(x)`, `try_conv_float(x)`, `try_conv_bool(x)` convert or return `None`.

```fallen
age =i conv_int(enter("Age: "))
write(age)

maybe =i try_conv_int("oops")
write(maybe)  # None
```

### amount(x)

Returns length of a list or string.

```fallen
write(amount([1,2,3]))
write(amount("abc"))
```

### del(list)

Removes and returns the last element of a list.

```fallen
nums =l [1, 2, 3]
write(del(nums))
write(nums)
```

### File I/O

- `save(path, text)` overwrite/create
- `change(path, text)` append
- `read(path)` read whole file

Paths are resolved relative to the program’s folder.

```fallen
save("note.txt", "hi")
change("note.txt", " there")
write(read("note.txt"))
```

## Lists

```fallen
nums =l [10, 20, 30]
```

### Read an element

Use `call <name>(<index>)`.

```fallen
write(call nums(0))
call nums(1)  # statement shortcut: prints the value
```

### Set / add / remove

```fallen
set nums(1) to (999)
add nums(42)
insert(nums, 0, 5)
remove nums(0)
write(nums)
```

## Dicts

```fallen
d =d {"name": "Ali"}
write(call d("name"))

set d("score") to (100)
remove d("name")
write(d)
```

## match

```fallen
x =i 2
match x {
    1 { write("one") }
    2 { write("two") }
    else { write("other") }
}
```

## Modules (import/export)

### import

```fallen
import "some_module.fallen"
```

Notes:

- A module is executed once per run (cached).
- Circular imports are handled safely.

### Private names and export

Rules:

- Names starting with `_` are private by default.
- If a module has no `export` statements: all non-underscore module globals are public.
- If a module uses `export` at least once: only exported names are public.

Syntax:

```fallen
export name
```

## Standard library (std/)

These modules ship as Fallen source files:

- `std/strings.fallen`: `concat(a,b)`, `repeat(s,n)`
- `std/lists.fallen`: `amount_list(x)`, `peek_last(x)`
- `std/files.fallen`: `read_text(path)`, `write_text(path,text)`, `append_text(path,text)`

Example:

```fallen
import "std/files.fallen"
save("std_test.txt", "hi")
write(read_text("std_test.txt"))
```

## Debugging

### Runtime errors (stack traces)

Runtime errors include a stack trace:

```text
Runtime error: ...
  ip=0006
  at func crash (file.fallen:3)
  at func main (file.fallen:7)
  at func <main> (file.fallen:10)
```

Import failures are shown as:

```text
Import error in "module.fallen":
  Runtime error: ...
  at func ...
```

### Trace mode (VM instruction tracing)

Use exactly:

- `trace on`
- `trace off`

When enabled, the VM prints each instruction as it executes:

```text
TRACE ip=0012 ('LOAD_CONST', 3) stack=2
```