# Fallen Language — instruction.md (Complete Reference)

This document is the **single source of truth** for how to write Fallen code.

It has two parts:

1. **Implemented (Confirmed)** — features that are clearly present in your current pipeline because they map to AST node types your CLI can print (`VarAssign`, `Literal`, `Binary`, `Call`, `If`, `While`, `Block`, etc.).
2. **Language Spec (Target / Intended)** — features you have defined in conversation (example: list `set/add`, `call()` indexing, `enter()`, `conv_int/conv_float`, boolean operators). If any of these are not yet implemented in your `Lexer/Parser/Compiler/VM`, treat them as the **required behavior** to implement next.

---

## Table of contents

- 1. Quick start
- 2. CLI commands
- 3. Core syntax rules
- 4. Data types and literals
- 5. Variables and assignment
- 6. Expressions and operators
- 7. Conditionals: `if`, `else`
- 8. Loops: `while`
- 9. Functions and calls
- 10. Built-in functions
- 11. Lists
- 12. Errors and debugging
- 13. Style guide
- 14. Examples (copy/paste)
- 15. Compatibility notes / roadmap

---

## 1) Quick start

Create a file `hello.fallen`:

```fallen
write("Hello, Fallen!")
```

Run it:
```
python cli.py run hello.fallen
```


## 2) CLI commands (Implemented / Confirmed)

Your CLI supports:

- Parse (print AST)
  ```bash
  python cli.py parse <file.fallen>
  ```
- Build (print constants + bytecode instructions)
  ```bash
  python cli.py build <file.fallen>
  ```
- Run (execute on VM)
  ```bash
  python cli.py run <file.fallen>
  ```

If the VM throws an exception:

```text
Runtime error: <message>
```

## 3) Core syntax rules (Implemented / Confirmed)

### Statements

A program is a list of statements executed top-to-bottom.

### Blocks

Curly braces define a block:

```fallen
{
    write("inside block")
}
```

Blocks are used by `if`, `else`, and `while`.

### Strings must use quotes

```fallen
"mmgc"  # string literal
mmgc    # variable name
```

### Undefined variables are runtime errors

If you reference a variable that does not exist, you should see:

```text
Runtime error: Undefined variable: <name>
```

## 4) Data types and literals

### 4.1 Literals (Implemented / Confirmed as `Literal` nodes)

Literals are values written directly in code.

Common literals:

```fallen
"hello"     # string
123         # integer
3.14        # float
true        # boolean
false       # boolean
```

The exact literal set is determined by your Lexer + Parser. The runtime receives them as `Literal.value`.

### 4.2 Types (Target / Intended)

Fallen uses typed assignment via a marker.

Recommended standard markers:

- `=s` string
- `=i` integer
- `=f` float
- `=b` boolean

Example:

```fallen
name =s "Ali"
age  =i 17
pi   =f 3.14
ok   =b true
```

## 5) Variables and assignment (Implemented / Confirmed)

### 5.1 Create / assign

General form:

```text
<name> =<type> <expression>
```

Examples:

```fallen
school =s "mmgc"
points =i 5
```

### 5.2 Re-assign

Assigning again overwrites the old value:

```fallen
points =i 10
points =i 11
```

## 6) Expressions and operators

### 6.1 Expressions (Implemented / Confirmed)

Your AST supports these expression shapes:

- Literal value
- Variable reference
- Binary operation
- Function call

Examples:

```fallen
"hello"                # literal
x                      # variable
x + 2                  # binary
write("hi")            # call
conv_int(enter("x"))   # nested calls
```

### 6.2 Operators (Implemented as `Binary` nodes; exact set depends on Lexer/Parser)

Arithmetic (Target / Intended)

```text
+   -   *   /
```

Example:

```fallen
total =i 5 + 3
```

Comparisons (Target / Intended)

```text
==  !=  <  <=  >  >=
```

Example:

```fallen
if score >= 50 {
    write("Pass")
}
```

Boolean logic (Target / Intended)

```text
and   or   not
```

Examples:

```fallen
if a == 1 and b == 2 {
    write("both true")
}

if role == "admin" or role == "moderator" {
    write("staff")
}

if not banned {
    write("welcome")
}
```

Implementation note: `not` is a unary operator. Many parsers represent it as a `Unary` node. If you don’t have a `Unary` node yet, you will need to add it (or treat `not x` as a special-case parse).

### 6.3 Operator precedence (Target / Intended)

Recommended precedence rules (highest to lowest):

1. Parentheses: `( ... )`
2. Unary: `not`, unary `-`
3. Multiply/divide: `*` `/`
4. Add/subtract: `+` `-`
5. Comparisons: `==` `!=` `<` `<=` `>` `>=`
6. Boolean: `and`
7. Boolean: `or`

Use parentheses when you want to be explicit:

```fallen
if (a == 1 or a == 2) and b == 9 {
    write("matched")
}
```

## 7) Conditionals: `if`, `else` (Implemented / Confirmed)

### 7.1 `if`

```fallen
if <condition> {
    <statements>
}
```

### 7.2 `if` + `else`

```fallen
if <condition> {
    <statements>
} else {
    <statements>
}
```

### 7.3 Example (including the “mmgc” fix)

Correct usage with quotes:

```fallen
value =s enter("what is the name of your school? ")

if value == "mmgc" {
    write("Falcon")
} else {
    write("Unknown school")
}
```

## 8) Loops: `while` (Implemented / Confirmed)

### 8.1 Syntax

```fallen
while <condition> {
    <statements>
}
```

### 8.2 Example

```fallen
i =i 0
while i < 3 {
    write(i)
    i =i i + 1
}
```

## 9) Functions and calls

### 9.1 Calls (Implemented / Confirmed as `Call` nodes)

A call looks like:

```text
name(arg1, arg2, arg3)
```

Examples:

```fallen
write("Hello")
enter("Type: ")
conv_int("123")
```

Arguments are expressions, so nesting is allowed:

```fallen
age =i conv_int(enter("Age: "))
write(age)
```

### 9.2 User-defined functions (Target / Intended)

If you want user-defined functions, the typical syntax is:

```fallen
func add(a, b) {
    return a + b
}

x =i add(5, 7)
write(x)
```

If this feature is not implemented yet, you will need new AST nodes (commonly `FuncDef` and `Return`) and compiler/VM support.

## 10) Built-in functions (Target / Intended)

These are the built-ins you have already chosen in the language design.

### 10.1 `write(value)`

Prints a value to the console.

```fallen
write("Hello")
write(123)
```

### 10.2 `enter(prompt)`

Shows a prompt, reads user input, returns a string.

```fallen
name =s enter("Enter your name: ")
write(name)
```

### 10.3 `conv_int(value)`

Converts a string to an integer.

```fallen
t =s enter("Enter a number: ")
n =i conv_int(t)
write(n)
```

Runtime rule: if conversion fails, the VM should error:

```text
Runtime error: Cannot convert to int: "abc"
```

### 10.4 `conv_float(value)`

Converts a string to a float.

```fallen
t =s enter("Enter a decimal: ")
x =f conv_float(t)
write(x)
```

Runtime rule: if conversion fails, the VM should error:

```text
Runtime error: Cannot convert to float: "abc"
```

## 11) Lists (Target / Intended)

### 11.1 Create a list

```fallen
my_list [1, "d", 2.2]
```

### 11.2 Read items using call

Index starts at 0.

```fallen
write(my_list(0))   # prints 1
write(my_list(1))   # prints "d"
write(my_list(2))   # prints 2.2
```

### 11.3 Print entire list

```fallen
write(my_list)
```

If you only want one output function in the language, standardize on `write()` and avoid adding a separate `print()`.

### 11.4 Change an element (`set`)

Syntax:

```text
set listname (index) to (value)
```

Example:

```fallen
nums [10, 20, 30]
set nums (0) to (2)     # nums becomes [2, 20, 30]
```

### 11.5 Add to end (append) (`add`)

Syntax:

```text
add listname (value)
```

Example:

```fallen
nums [1, 2]
add nums (99)           # nums becomes [1, 2, 99]
```

## 12) Errors and debugging

### 12.1 Common runtime errors

#### Undefined variable

Cause: using a name that was never assigned.

Example:

```fallen
write(mmgc)
```

Fix: assign it or quote it as a string:

```fallen
write("mmgc")
```

#### Bad conversion

Cause: `conv_int("abc")`

Fix: ensure numeric input, or validate before converting (if you later add validation helpers).

### 12.2 Recommended debugging workflow

Run:

```bash
python cli.py parse file.fallen
```

Confirm the AST matches what you think you wrote.

Run:

```bash
python cli.py build file.fallen
```

Confirm constants and instruction order.

Run:

```bash
python cli.py run file.fallen
```

If it fails, use the error message + AST output to locate the problem.

## 13) Style guide (recommended)

Use clear variable names:

```fallen
user_name =s enter("Name: ")
```

Use parentheses in complex boolean expressions:

```fallen
if (a == 1 or a == 2) and not banned {
    write("ok")
}
```

Prefer one output function (`write`) to keep the language simple.

## 14) Examples (copy/paste)

### 14.1 Echo input

```fallen
msg =s enter("Enter something: ")
write(msg)
```

### 14.2 School check (your real example)

```fallen
value =s enter("what is the name of your school? ")
if value == "mmgc" {
    write("Falcon")
} else {
    write("Not mmgc")
}
```

### 14.3 While loop counter

```fallen
i =i 0
while i < 5 {
    write(i)
    i =i i + 1
}
```

### 14.4 Conversions

```fallen
a =s enter("Enter whole number: ")
b =i conv_int(a)
write(b)

x =s enter("Enter decimal: ")
y =f conv_float(x)
write(y)
```

### 14.5 Lists (design spec)

```fallen
items [1, "d", 2.2]
write(items(0))
set items (0) to (2)
add items (99)
write(items)
```

## 15) Compatibility notes / roadmap

Confirmed by your current AST printer

These are definitely present in your language pipeline:

- Typed assignment structure (`VarAssign` with `name`, `var_type`, `value`)
- Literals (`Literal`)
- Variable reads (`Var`)
- Binary expressions (`Binary`)
- Calls (`Call`)
- Blocks (`Block`)
- `if` / optional `else` (`If`)
- `while` (`While`)

Spec-defined features to ensure are implemented

These are required by your design and should be implemented if missing:

- `enter("prompt")`
- `conv_int(x)` and `conv_float(x)`
- boolean operators: `and`, `or`, `not`
- list creation, indexing via call, plus `set` and `add`