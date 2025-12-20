import os
import sys


class FallenError(Exception):
    pass


class FallenRuntimeError(FallenError):
    def __init__(self, message: str, ip: int | None = None, frames=None):
        super().__init__(message)
        self.message = message
        self.ip = ip
        self.frames = frames or []  # most recent first

    def format(self, indent: str = "") -> str:
        lines = [f"{indent}Runtime error: {self.message}"]
        if self.ip is not None:
            lines.append(f"{indent}  ip={self.ip:04d}")
        for fr in self.frames:
            func = fr.get("func", "<unknown>")
            file_path = fr.get("file") or "<unknown>"
            file_short = os.path.basename(file_path)
            line = fr.get("line")
            if line is None:
                loc = f"{file_short}:ip={fr.get('ip', '?')}"
            else:
                loc = f"{file_short}:{line}"
            lines.append(f"{indent}  at func {func} ({loc})")
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.format()


class FallenImportError(FallenError):
    def __init__(self, path_literal: str, message: str | None = None, inner: FallenRuntimeError | None = None):
        super().__init__(message or "import error")
        self.path_literal = path_literal
        self.message = message
        self.inner = inner

    def __str__(self) -> str:
        if self.inner is None:
            if self.message:
                return f"Import error: {self.message} \"{self.path_literal}\""
            return f"Import error: \"{self.path_literal}\""

        lines = [f"Import error in \"{self.path_literal}\":"]
        lines.append(self.inner.format(indent="  "))
        return "\n".join(lines)


class VM:
    def __init__(self, bytecode_program, base_dir=None, entry_file: str | None = None, argv=None):
        self.consts = bytecode_program.consts
        self.instructions = bytecode_program.instructions
        self.debug = getattr(bytecode_program, "debug", [None] * len(self.instructions))
        self.functions = getattr(bytecode_program, "functions", {})

        self.base_dir = base_dir or os.getcwd()
        self.modules_loaded = set()   # (abs path, alias) tuples already imported
        self.modules_loading = set()  # (abs path, alias) tuples currently executing

        self.MAX_CALL_DEPTH = 1000
        self.max_steps = None  # set to an int to guard against infinite loops

        self.ip = 0                 # instruction pointer (where we are)
        self.stack = []             # stack for values
        self.globals = {}           # global variables
        self.env = self.globals     # current local env (globals at top-level)
        self.call_stack = []        # list of frames

        self.current_function_name = "<main>"
        self.entry_file_path = os.path.normpath(os.path.abspath(entry_file)) if entry_file else None
        self.current_file_path = self.entry_file_path

        self.trace_enabled = False

        # Script arguments passed from the CLI (strings only)
        if argv is None:
            self.argv = []
        else:
            self.argv = [str(x) for x in argv]

        # Best-effort Windows ANSI support (only used if colors are requested)
        self._colorama_inited = False

    def _ensure_colorama(self):
        if self._colorama_inited:
            return
        self._colorama_inited = True
        try:
            # Optional dependency; if present, enables ANSI in Windows terminals.
            import colorama  # type: ignore

            colorama.just_fix_windows_console()
        except Exception:
            pass

    def _is_ident(self, s: str) -> bool:
        if not s:
            return False
        if not (s[0].isalpha() or s[0] == "_"):
            return False
        for ch in s[1:]:
            if not (ch.isalnum() or ch == "_"):
                return False
        return True

    def _format_string(self, fmt: str) -> str:
        out = []
        i = 0
        n = len(fmt)
        while i < n:
            ch = fmt[i]
            if ch == "{":
                j = fmt.find("}", i + 1)
                if j == -1:
                    raise Exception("Invalid format string")
                name = fmt[i + 1 : j]
                if not self._is_ident(name):
                    raise Exception("Invalid format string")

                if name in self.env:
                    value = self.env[name]
                elif name in self.globals:
                    value = self.globals[name]
                else:
                    raise Exception(f"Undefined variable in format string: {name}")

                out.append(str(value))
                i = j + 1
                continue

            if ch == "}":
                raise Exception("Invalid format string")

            out.append(ch)
            i += 1
        return "".join(out)

    def add_const(self, value):
        # reuse constants if already added
        try:
            if value in self.consts:
                return self.consts.index(value)
        except Exception:
            # fallback: just append
            pass
        self.consts.append(value)
        return len(self.consts) - 1

    def resolve_path(self, path: str) -> str:
        if os.path.isabs(path):
            return os.path.normpath(path)
        return os.path.normpath(os.path.join(self.base_dir, path))

    def resolve_import_path(self, path: str) -> str:
        if os.path.isabs(path):
            return os.path.normpath(path)

        # Prefer importing relative to the entry file folder (base_dir).
        candidate = os.path.normpath(os.path.join(self.base_dir, path))
        if os.path.exists(candidate):
            return candidate

        # Fallback: allow importing from the project root when entry is in a subfolder (e.g. tests/).
        parent = os.path.dirname(os.path.normpath(self.base_dir))
        candidate2 = os.path.normpath(os.path.join(parent, path))
        if os.path.exists(candidate2):
            return candidate2

        return candidate

    def _debug_at_ip(self, ip: int):
        if ip < 0 or ip >= len(self.debug):
            return None
        return self.debug[ip]

    def _location_for_ip(self, ip: int):
        dbg = self._debug_at_ip(ip) or {}
        file_path = dbg.get("file") or self.current_file_path
        line = dbg.get("line")
        return file_path, line

    def build_stacktrace(self):
        frames = []

        # current frame
        file_path, line = self._location_for_ip(self.ip)
        frames.append({
            "func": self.current_function_name,
            "file": file_path,
            "line": line,
            "ip": self.ip,
        })

        # callers (most recent first)
        for fr in reversed(self.call_stack):
            call_ip = fr.get("call_ip")
            call_file = fr.get("call_file")
            call_line = fr.get("call_line")
            if call_ip is not None and call_file is None:
                dbg = self._debug_at_ip(call_ip) or {}
                call_file = dbg.get("file")
                call_line = dbg.get("line")
            frames.append({
                "func": fr.get("caller_func", "<unknown>"),
                "file": call_file,
                "line": call_line,
                "ip": call_ip,
            })

        return frames

    def check_ip(self, target: int, context: str):
        if not isinstance(target, int):
            raise Exception(f"Invalid jump target for {context}: {target}")
        if target < 0 or target >= len(self.instructions):
            raise Exception(f"Invalid jump target for {context}: {target}")

    def pop(self):
        if not self.stack:
            raise Exception("Stack underflow")
        return self.stack.pop()

    def require_bool(self, value, context: str) -> bool:
        if isinstance(value, bool):
            return value
        raise Exception(f"{context} must be boolean")

    def conv_int(self, value):
        if value is None:
            raise Exception("cannot convert None to int")
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            s = value.strip()
            if s == "":
                raise Exception("cannot convert empty string to int")
            try:
                return int(s)
            except Exception:
                raise Exception(f"cannot convert string to int: {value}")
        raise Exception(f"cannot convert {type(value).__name__} to int")

    def conv_float(self, value):
        if value is None:
            raise Exception("cannot convert None to float")
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            s = value.strip()
            if s == "":
                raise Exception("cannot convert empty string to float")
            try:
                return float(s)
            except Exception:
                raise Exception(f"cannot convert string to float: {value}")
        raise Exception(f"cannot convert {type(value).__name__} to float")

    def conv_bool(self, value):
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            s = value.strip().lower()
            if s in ("true", "1", "yes", "y", "on"):
                return True
            if s in ("false", "0", "no", "n", "off", ""):
                return False
            raise Exception(f"cannot convert string to bool: {value}")
        raise Exception(f"cannot convert {type(value).__name__} to bool")

    def _check_return_type(self, func_name: str, value, type_code: str):
        if type_code is None:
            return
        if type_code == "s":
            ok = isinstance(value, str)
        elif type_code == "i":
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif type_code == "f":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif type_code == "b":
            ok = isinstance(value, bool)
        elif type_code == "l":
            ok = isinstance(value, list)
        elif type_code == "d":
            ok = isinstance(value, dict)
        else:
            raise Exception(f"Unknown return type: {type_code}")

        if not ok:
            got = "None" if value is None else type(value).__name__
            raise Exception(f"Return type mismatch in {func_name}(): expected {type_code}, got {got}")

    def link_bytecode(self, bc):
        base_ip = len(self.instructions)

        const_map = {}
        for i, c in enumerate(bc.consts):
            const_map[i] = self.add_const(c)

        for opcode, arg in bc.instructions:
            if opcode == "LOAD_CONST":
                self.instructions.append((opcode, const_map[arg]))
                continue
            if opcode in ("JUMP", "JUMP_IF_FALSE"):
                if arg is None:
                    raise Exception(f"Invalid jump target in imported module: {arg}")
                self.instructions.append((opcode, arg + base_ip))
                continue
            self.instructions.append((opcode, arg))

        # debug info
        bc_debug = getattr(bc, "debug", None)
        if bc_debug is None:
            bc_debug = [None] * len(bc.instructions)
        for opcode, dbg in zip(bc.instructions, bc_debug, strict=False):
            self.debug.append(dbg)

        for name, meta in getattr(bc, "functions", {}).items():
            entry = meta.get("entry")
            if entry is None:
                continue
            if name in self.functions:
                raise Exception(f"Function already defined: {name}")
            self.functions[name] = {
                "entry": entry + base_ip,
                "params": list(meta.get("params", [])),
                "file": meta.get("file"),
            }

        return base_ip, len(self.instructions)

    def run_range(self, start_ip: int, end_ip: int):
        saved_ip = self.ip
        self.ip = start_ip
        try:
            while self.ip < end_ip:
                halted = self.step()
                if halted:
                    break
        finally:
            self.ip = saved_ip

    def _module_public_symbols(self, bc):
        defined = set(getattr(bc, "defined_globals", set()) or set())
        exports = set(getattr(bc, "exports", set()) or set())

        if exports:
            public = exports
        else:
            public = {name for name in defined if not name.startswith("_")}

        private = defined - public
        return defined, public, private

    def import_module(self, path: str, alias: str | None = None):
        module_path = self.resolve_import_path(path)
        alias_key = str(alias) if alias is not None else None
        import_key = (module_path, alias_key)
        if import_key in self.modules_loaded:
            return
        if import_key in self.modules_loading:
            # safe circular import handling: ignore re-entry
            return

        self.modules_loading.add(import_key)
        try:
            if not os.path.exists(module_path):
                raise FallenImportError(path, message="file not found")

            try:
                with open(module_path, "r", encoding="utf-8") as f:
                    source = f.read()
            except Exception:
                raise FallenImportError(path, message="cannot read file")

            try:
                from lexer import Lexer
                from parser import Parser
                from compiler import Compiler

                lexer = Lexer(source)
                parser = Parser(lexer)
                program = parser.parse()
                compiler = Compiler(source_path=module_path)
                bc = compiler.compile(program)
            except FallenError:
                raise
            except Exception as e:
                raise FallenImportError(path, message=str(e))

            # Enforce module export/private rules by rewriting private symbols to internal names.
            # This prevents leaking helpers while still allowing exported code to call private helpers.
            self._apply_module_visibility(bc, module_path, instance_tag=alias_key)

            # Optional alias import: rewrite public symbols to alias-prefixed names.
            if alias_key is not None:
                self._apply_import_alias(bc, alias_key)

            start_ip, end_ip = self.link_bytecode(bc)

            saved_env = self.env
            saved_func = self.current_function_name
            saved_file = self.current_file_path
            saved_ip = self.ip
            self.env = self.globals
            self.current_function_name = "<module>"
            self.current_file_path = module_path
            try:
                try:
                    self.ip = start_ip
                    while self.ip < end_ip:
                        halted = self.step()
                        if halted:
                            break
                except FallenRuntimeError as e:
                    raise FallenImportError(path, inner=e)
                except Exception as e:
                    raise FallenImportError(path, inner=FallenRuntimeError(str(e), ip=self.ip, frames=self.build_stacktrace()))
            finally:
                self.env = saved_env
                self.current_function_name = saved_func
                self.current_file_path = saved_file
                self.ip = saved_ip

            self.modules_loaded.add(import_key)
        finally:
            self.modules_loading.discard(import_key)

    def _apply_module_visibility(self, bc, module_path: str, instance_tag: str | None = None):
        _, public, private = self._module_public_symbols(bc)
        if not private:
            return

        tag = ""
        if instance_tag:
            tag = f"{instance_tag}:"
        prefix = f"$mod:{os.path.normpath(os.path.abspath(module_path))}:{tag}"
        mapping = {name: f"{prefix}{name}" for name in private}

        # Rewrite instruction operands.
        new_instructions = []
        for opcode, arg in bc.instructions:
            if opcode in ("LOAD_NAME", "STORE_NAME") and isinstance(arg, str) and arg in mapping:
                arg = mapping[arg]
            elif opcode == "CALL_FUNC":
                if isinstance(arg, tuple) and len(arg) == 3:
                    name, argc, arg_names = arg
                    if name in mapping:
                        arg = (mapping[name], argc, arg_names)
                else:
                    name, argc = arg
                    if name in mapping:
                        arg = (mapping[name], argc)
            new_instructions.append((opcode, arg))
        bc.instructions = new_instructions

        # Rewrite function table keys.
        new_functions = {}
        for name, meta in getattr(bc, "functions", {}).items():
            new_name = mapping.get(name, name)
            new_functions[new_name] = meta
        bc.functions = new_functions

    def _apply_import_alias(self, bc, alias: str):
        _, public, _ = self._module_public_symbols(bc)
        if not public:
            return

        mapping = {name: f"{alias}_{name}" for name in public}

        new_instructions = []
        for opcode, arg in bc.instructions:
            if opcode in ("LOAD_NAME", "STORE_NAME") and isinstance(arg, str) and arg in mapping:
                arg = mapping[arg]
            elif opcode == "CALL_FUNC":
                if isinstance(arg, tuple) and len(arg) == 3:
                    name, argc, arg_names = arg
                    if name in mapping:
                        arg = (mapping[name], argc, arg_names)
                else:
                    name, argc = arg
                    if name in mapping:
                        arg = (mapping[name], argc)
            new_instructions.append((opcode, arg))
        bc.instructions = new_instructions

        new_functions = {}
        for name, meta in getattr(bc, "functions", {}).items():
            new_name = mapping.get(name, name)
            new_functions[new_name] = meta
        bc.functions = new_functions

    def step(self) -> bool:
        self.check_ip(self.ip, "ip")
        opcode, arg = self.instructions[self.ip]

        if self.trace_enabled:
            print(f"TRACE ip={self.ip:04d} {(opcode, arg)!r} stack={len(self.stack)}")

        if opcode == "SET_TRACE":
            self.trace_enabled = bool(arg)
            self.ip += 1
            return False

        if opcode == "LOAD_CONST":
            self.stack.append(self.consts[arg])
            self.ip += 1
            return False

        if opcode == "FORMAT_STRING":
            fmt = self.pop()
            if not isinstance(fmt, str):
                raise Exception("format string must be a string")
            self.stack.append(self._format_string(fmt))
            self.ip += 1
            return False

        if opcode == "LOAD_NAME":
            name = arg
            if name in self.env:
                self.stack.append(self.env[name])
            elif name in self.globals:
                self.stack.append(self.globals[name])
            else:
                raise Exception(f"Undefined name: {name}")
            self.ip += 1
            return False

        if opcode == "STORE_NAME":
            self.env[arg] = self.pop()
            self.ip += 1
            return False

        if opcode == "POP":
            self.pop()
            self.ip += 1
            return False

        if opcode == "DUP":
            if not self.stack:
                raise Exception("Stack underflow")
            self.stack.append(self.stack[-1])
            self.ip += 1
            return False

        if opcode in ("ADD", "SUB", "MUL", "DIV"):
            b = self.pop()
            a = self.pop()
            try:
                if opcode == "ADD":
                    self.stack.append(a + b)
                elif opcode == "SUB":
                    self.stack.append(a - b)
                elif opcode == "MUL":
                    self.stack.append(a * b)
                else:
                    self.stack.append(a / b)
            except Exception as e:
                raise Exception(str(e))
            self.ip += 1
            return False

        if opcode.startswith("CMP_"):
            b = self.pop()
            a = self.pop()
            if opcode == "CMP_EQ":
                self.stack.append(a == b)
            elif opcode == "CMP_NE":
                self.stack.append(a != b)
            elif opcode == "CMP_LT":
                self.stack.append(a < b)
            elif opcode == "CMP_LE":
                self.stack.append(a <= b)
            elif opcode == "CMP_GT":
                self.stack.append(a > b)
            elif opcode == "CMP_GE":
                self.stack.append(a >= b)
            else:
                raise Exception(f"Unknown compare opcode: {opcode}")
            self.ip += 1
            return False

        if opcode == "NOT":
            a = self.require_bool(self.pop(), "not")
            self.stack.append(not a)
            self.ip += 1
            return False

        if opcode == "BUILD_LIST":
            count = arg
            items = []
            for _ in range(count):
                items.append(self.pop())
            items.reverse()
            self.stack.append(items)
            self.ip += 1
            return False

        if opcode == "BUILD_DICT":
            count = arg
            d = {}
            for _ in range(count):
                value = self.pop()
                key = self.pop()
                if not isinstance(key, str):
                    raise Exception("dict keys must be strings")
                d[key] = value
            self.stack.append(d)
            self.ip += 1
            return False

        if opcode == "LIST_GET":
            index = self.pop()
            target = self.pop()
            if not isinstance(target, list):
                raise Exception("target not a list")
            if not isinstance(index, int):
                raise Exception("index not integer")
            if index < 0 or index >= len(target):
                raise Exception("index out of range")
            self.stack.append(target[index])
            self.ip += 1
            return False

        if opcode == "LIST_APPEND":
            value = self.pop()
            target = self.pop()
            if not isinstance(target, list):
                raise Exception("target not a list")
            target.append(value)
            self.ip += 1
            return False

        if opcode == "INDEX_GET":
            key = self.pop()
            target = self.pop()
            if isinstance(target, list):
                if not isinstance(key, int):
                    raise Exception("index not integer")
                if key < 0 or key >= len(target):
                    raise Exception("index out of range")
                self.stack.append(target[key])
            elif isinstance(target, dict):
                if not isinstance(key, str):
                    raise Exception("dict key must be string")
                if key not in target:
                    raise Exception(f"key not found: {key}")
                self.stack.append(target[key])
            else:
                raise Exception("target not indexable")
            self.ip += 1
            return False

        if opcode == "INDEX_SET":
            value = self.pop()
            key = self.pop()
            target = self.pop()
            if isinstance(target, list):
                if not isinstance(key, int):
                    raise Exception("index not integer")
                if key < 0 or key >= len(target):
                    raise Exception("index out of range")
                target[key] = value
            elif isinstance(target, dict):
                if not isinstance(key, str):
                    raise Exception("dict key must be string")
                target[key] = value
            else:
                raise Exception("target not indexable")
            self.ip += 1
            return False

        if opcode == "INDEX_REMOVE":
            key = self.pop()
            target = self.pop()
            if isinstance(target, list):
                if not isinstance(key, int):
                    raise Exception("index not integer")
                if key < 0 or key >= len(target):
                    raise Exception("index out of range")
                del target[key]
            elif isinstance(target, dict):
                if not isinstance(key, str):
                    raise Exception("dict key must be string")
                if key not in target:
                    raise Exception(f"key not found: {key}")
                del target[key]
            else:
                raise Exception("target not indexable")
            self.ip += 1
            return False

        if opcode == "JUMP":
            self.check_ip(arg, "jump")
            self.ip = arg
            return False

        if opcode == "JUMP_IF_FALSE":
            condition = self.require_bool(self.pop(), "condition")
            if condition is False:
                self.check_ip(arg, "jump")
                self.ip = arg
            else:
                self.ip += 1
            return False

        if opcode == "CALL_BUILTIN":
            name, argc = arg
            args = []
            for _ in range(argc):
                args.append(self.pop())
            args.reverse()

            if name == "write":
                if argc not in (1, 2):
                    raise Exception("write() must have 1 or 2 arguments")

                text = str(args[0])
                color = None
                if argc == 2:
                    color = str(args[1]).strip().lower()

                ansi_colors = {
                    "gray": "90",
                    "red": "31",
                    "green": "32",
                    "yellow": "33",
                    "blue": "34",
                    "magenta": "35",
                    "cyan": "36",
                    "white": "37",
                }

                def apply_color(s: str, cname: str | None) -> str:
                    if not cname:
                        return s
                    code = ansi_colors.get(cname)
                    if not code:
                        return s
                    self._ensure_colorama()
                    return f"\x1b[{code}m{s}\x1b[0m"

                # Tagged text form: [red]...[/red]
                if color is None and "[" in text and "]" in text:
                    for cname in ansi_colors.keys():
                        open_tag = f"[{cname}]"
                        close_tag = f"[/{cname}]"
                        i = text.find(open_tag)
                        if i == -1:
                            continue
                        j = text.find(close_tag, i + len(open_tag))
                        if j == -1:
                            continue
                        inner = text[i + len(open_tag) : j]
                        text = text[:i] + apply_color(inner, cname) + text[j + len(close_tag) :]
                        break

                # Arg form: write(text, "red")
                text = apply_color(text, color)
                print(text)

            elif name == "enter":
                if argc != 1:
                    raise Exception("enter() must have exactly 1 argument")
                prompt = str(args[0])
                self.stack.append(input(prompt))

            elif name == "args":
                if argc != 0:
                    raise Exception("args() must have exactly 0 arguments")
                self.stack.append(list(self.argv))

            elif name == "conv_int":
                if argc != 1:
                    raise Exception("conv_int() must have exactly 1 argument")
                self.stack.append(self.conv_int(args[0]))
            elif name == "conv_float":
                if argc != 1:
                    raise Exception("conv_float() must have exactly 1 argument")
                self.stack.append(self.conv_float(args[0]))
            elif name == "conv_bool":
                if argc != 1:
                    raise Exception("conv_bool() must have exactly 1 argument")
                self.stack.append(self.conv_bool(args[0]))

            elif name == "try_conv_int":
                if argc != 1:
                    raise Exception("try_conv_int() must have exactly 1 argument")
                try:
                    self.stack.append(self.conv_int(args[0]))
                except Exception:
                    self.stack.append(None)
            elif name == "try_conv_float":
                if argc != 1:
                    raise Exception("try_conv_float() must have exactly 1 argument")
                try:
                    self.stack.append(self.conv_float(args[0]))
                except Exception:
                    self.stack.append(None)
            elif name == "try_conv_bool":
                if argc != 1:
                    raise Exception("try_conv_bool() must have exactly 1 argument")
                try:
                    self.stack.append(self.conv_bool(args[0]))
                except Exception:
                    self.stack.append(None)

            elif name == "amount":
                if argc != 1:
                    raise Exception("amount() must have exactly 1 argument")
                v = args[0]
                if isinstance(v, (list, str)):
                    self.stack.append(len(v))
                else:
                    raise Exception("amount() expects list or string")

            elif name == "del":
                if argc != 1:
                    raise Exception("del() must have exactly 1 argument")
                v = args[0]
                if not isinstance(v, list):
                    raise Exception("target not a list")
                if len(v) == 0:
                    raise Exception("del() on empty list")
                self.stack.append(v.pop())

            elif name == "upper":
                if argc != 1:
                    raise Exception("upper() must have exactly 1 argument")
                self.stack.append(str(args[0]).upper())

            elif name == "lower":
                if argc != 1:
                    raise Exception("lower() must have exactly 1 argument")
                self.stack.append(str(args[0]).lower())

            elif name == "split":
                if argc != 2:
                    raise Exception("split() must have exactly 2 arguments")
                s = str(args[0])
                sep = str(args[1])
                self.stack.append(s.split(sep))

            elif name == "join":
                if argc != 2:
                    raise Exception("join() must have exactly 2 arguments")
                items = args[0]
                sep = str(args[1])
                if not isinstance(items, list):
                    raise Exception("join() expects a list")
                self.stack.append(sep.join(str(x) for x in items))

            elif name == "replace":
                if argc != 3:
                    raise Exception("replace() must have exactly 3 arguments")
                s = str(args[0])
                old = str(args[1])
                new = str(args[2])
                self.stack.append(s.replace(old, new))

            elif name == "insert":
                if argc != 3:
                    raise Exception("insert() must have exactly 3 arguments")
                target = args[0]
                index = args[1]
                value = args[2]
                if not isinstance(target, list):
                    raise Exception("insert() expects a list")
                if not isinstance(index, int):
                    raise Exception("insert() index must be int")
                if index < 0 or index > len(target):
                    raise Exception("insert() index out of range")
                target.insert(index, value)
                self.stack.append(True)

            elif name == "save":
                if argc != 2:
                    raise Exception("save() must have exactly 2 arguments")
                path = self.resolve_path(str(args[0]))
                text = str(args[1])
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(text)
                except Exception:
                    raise Exception(f"cannot write file: {path}")
                self.stack.append(True)

            elif name in ("append", "change"):
                if argc != 2:
                    raise Exception(f"{name}() must have exactly 2 arguments")
                path = self.resolve_path(str(args[0]))
                text = str(args[1])
                try:
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(text)
                except Exception:
                    raise Exception(f"cannot write file: {path}")
                self.stack.append(True)

            elif name in ("load", "read"):
                if argc != 1:
                    raise Exception(f"{name}() must have exactly 1 argument")
                path = self.resolve_path(str(args[0]))
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = f.read()
                except Exception:
                    raise Exception(f"cannot read file: {path}")
                self.stack.append(data)

            else:
                raise Exception(f"Unknown builtin: {name}")

            self.ip += 1
            return False

        if opcode == "CALL_FUNC":
            arg_names = None
            if isinstance(arg, tuple) and len(arg) == 3:
                name, argc, arg_names = arg
            else:
                name, argc = arg
            if name not in self.functions:
                raise Exception(f"Unknown function: {name}")

            meta = self.functions[name]
            entry = meta.get("entry")
            if entry is None:
                raise Exception(f"Unknown function: {name}")

            param_names = meta.get("params", [])
            defaults = meta.get("defaults", {}) or {}
            expected = len(param_names)

            args = []
            for _ in range(argc):
                args.append(self.pop())
            args.reverse()

            if arg_names is not None:
                if not isinstance(arg_names, list) or len(arg_names) != argc:
                    raise Exception("Invalid call argument metadata")
                positional = []
                named = []
                for nm, val in zip(arg_names, args, strict=False):
                    if nm is None:
                        positional.append(val)
                    else:
                        named.append((nm, val))
            else:
                positional = args
                named = []

            if len(positional) > expected:
                raise Exception(f"{name}() expects at most {expected} positional arguments, got {len(positional)}")

            assigned = {}
            for i, val in enumerate(positional):
                assigned[param_names[i]] = val

            param_set = set(param_names)
            for nm, val in named:
                if nm not in param_set:
                    raise Exception(f"{name}() got an unexpected named argument: {nm}")
                if nm in assigned:
                    raise Exception(f"{name}() got multiple values for argument: {nm}")
                assigned[nm] = val

            final_args = []
            for pname in param_names:
                if pname in assigned:
                    final_args.append(assigned[pname])
                elif pname in defaults:
                    final_args.append(defaults[pname])
                else:
                    raise Exception(f"{name}() missing required argument: {pname}")

            if len(self.call_stack) >= self.MAX_CALL_DEPTH:
                raise Exception(f"Max call depth exceeded ({self.MAX_CALL_DEPTH})")

            call_ip = self.ip
            dbg = self._debug_at_ip(call_ip) or {}
            self.call_stack.append({
                "return_ip": self.ip + 1,
                "caller_env": self.env,
                "caller_func": self.current_function_name,
                "caller_file": self.current_file_path,
                "call_ip": call_ip,
                "call_file": dbg.get("file"),
                "call_line": dbg.get("line"),
            })

            local_env = {}
            for i, pname in enumerate(param_names):
                local_env[pname] = final_args[i]
            self.env = local_env

            self.current_function_name = name
            self.current_file_path = meta.get("file") or self.current_file_path
            self.check_ip(entry, "call")
            self.ip = entry
            return False

        if opcode == "RETURN":
            ret = self.pop() if self.stack else None
            if not self.call_stack:
                raise Exception("return used outside of a function")

            meta = self.functions.get(self.current_function_name, {}) or {}
            ret_type = meta.get("return_type")
            if ret_type is not None:
                self._check_return_type(self.current_function_name, ret, ret_type)

            fr = self.call_stack.pop()
            self.env = fr["caller_env"]
            self.current_function_name = fr.get("caller_func", "<main>")
            self.current_file_path = fr.get("caller_file")
            self.stack.append(ret)
            self.ip = fr["return_ip"]
            return False

        if opcode == "IMPORT":
            path = self.pop()
            if not isinstance(path, str):
                raise Exception("import path must be a string")
            try:
                alias = arg if isinstance(arg, str) else None
                self.import_module(path, alias=alias)
            except FallenImportError:
                raise
            except FallenRuntimeError as e:
                raise FallenImportError(path, inner=e)
            except Exception as e:
                raise FallenImportError(path, inner=FallenRuntimeError(str(e), ip=self.ip, frames=self.build_stacktrace()))
            self.ip += 1
            return False

        if opcode == "HALT":
            return True

        raise Exception(f"Unknown opcode: {opcode}")

    def run(self):
        steps = 0
        entry_marked = False
        if self.entry_file_path:
            self.modules_loading.add((self.entry_file_path, None))
            entry_marked = True
        try:
            while True:
                if self.max_steps is not None:
                    steps += 1
                    if steps > self.max_steps:
                        raise Exception("Step limit exceeded (possible infinite loop)")

                halted = self.step()
                if halted:
                    break
            if entry_marked:
                self.modules_loaded.add((self.entry_file_path, None))
        except FallenError:
            raise
        except Exception as e:
            raise FallenRuntimeError(str(e), ip=self.ip, frames=self.build_stacktrace())
        finally:
            if entry_marked:
                self.modules_loading.discard((self.entry_file_path, None))
