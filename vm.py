class VM:
    def __init__(self, bytecode_program):
        self.consts = bytecode_program.consts
        self.instructions = bytecode_program.instructions
        self.functions = getattr(bytecode_program, "functions", {})

        self.MAX_CALL_DEPTH = 1000
        self.max_steps = None  # set to an int to guard against infinite loops

        self.ip = 0                 # instruction pointer (where we are)
        self.stack = []             # stack for values
        self.globals = {}           # global variables
        self.env = self.globals     # current local env (globals at top-level)
        self.call_stack = []        # list of (return_ip, caller_env)

    def pop(self):
        if not self.stack:
            raise Exception("Stack underflow")
        return self.stack.pop()

    def require_bool(self, value, context="value"):
        if not isinstance(value, bool):
            raise Exception(f"Expected boolean for {context}, got {type(value).__name__}")
        return value

    def check_ip(self, target, context="jump"):
        if not isinstance(target, int):
            raise Exception(f"Invalid {context} target: {target}")
        if target < 0 or target >= len(self.instructions):
            raise Exception(f"Invalid {context} target: {target}")

    def format_conv_value(self, value):
        if isinstance(value, str):
            return value
        return str(value)

    def conv_int(self, value):
        try:
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value)
            if isinstance(value, str):
                s = value.strip()
                return int(s)
        except Exception:
            pass
        raise Exception(f"cannot convert \"{self.format_conv_value(value)}\" to int")

    def conv_float(self, value):
        try:
            if isinstance(value, bool):
                return float(value)
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                s = value.strip()
                return float(s)
        except Exception:
            pass
        raise Exception(f"cannot convert \"{self.format_conv_value(value)}\" to float")

    def conv_bool(self, value):
        # Rules (exact):
        # - bool: return as-is
        # - number: 0 -> false, non-zero -> true
        # - string: trimmed, case-insensitive:
        #     true:  true, 1, yes, y, on
        #     false: false, 0, no, n, off
        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            return value != 0

        if isinstance(value, str):
            s = value.strip().lower()
            if s in ("true", "1", "yes", "y", "on"):
                return True
            if s in ("false", "0", "no", "n", "off"):
                return False
            raise Exception(f"cannot convert \"{self.format_conv_value(value)}\" to bool")

        raise Exception(f"cannot convert \"{self.format_conv_value(value)}\" to bool")

    def run(self):
        steps = 0
        while True:
            if self.ip < 0 or self.ip >= len(self.instructions):
                raise Exception(f"Instruction pointer out of range: {self.ip}")

            if self.max_steps is not None:
                steps += 1
                if steps > self.max_steps:
                    raise Exception("Step limit exceeded (possible infinite loop)")

            opcode, arg = self.instructions[self.ip]

            if opcode == "LOAD_CONST":
                value = self.consts[arg]
                self.stack.append(value)
                self.ip += 1

            elif opcode == "LOAD_NAME":
                if arg in self.env:
                    self.stack.append(self.env[arg])
                elif arg in self.globals:
                    self.stack.append(self.globals[arg])
                else:
                    raise Exception(f"Undefined variable: {arg}")
                self.ip += 1

            elif opcode == "STORE_NAME":
                value = self.pop()
                # store goes to current scope (local inside a function, globals at top-level)
                self.env[arg] = value
                self.ip += 1

            elif opcode == "ADD":
                b = self.pop()
                a = self.pop()
                self.stack.append(a + b)
                self.ip += 1

            elif opcode == "SUB":
                b = self.pop()
                a = self.pop()
                self.stack.append(a - b)
                self.ip += 1

            elif opcode == "MUL":
                b = self.pop()
                a = self.pop()
                self.stack.append(a * b)
                self.ip += 1

            elif opcode == "DIV":
                b = self.pop()
                a = self.pop()
                self.stack.append(a / b)
                self.ip += 1

            elif opcode == "DUP":
                if not self.stack:
                    raise Exception("Stack underflow")
                self.stack.append(self.stack[-1])
                self.ip += 1

            elif opcode == "NOT":
                a = self.pop()
                a = self.require_bool(a, "not")
                self.stack.append(not a)
                self.ip += 1

            elif opcode.startswith("CMP_"):
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

            elif opcode == "JUMP_IF_FALSE":
                condition = self.pop()
                condition = self.require_bool(condition, "condition")
                if condition is False:
                    self.check_ip(arg, "jump")
                    self.ip = arg
                else:
                    self.ip += 1

            elif opcode == "JUMP":
                self.check_ip(arg, "jump")
                self.ip = arg

            elif opcode == "CALL_BUILTIN":
                name, argc = arg

                # pop args in reverse order, then flip them back
                args = []
                for _ in range(argc):
                    args.append(self.pop())
                args.reverse()

                if name == "write":
                    # prints one value (your rule)
                    if argc != 1:
                        raise Exception("write() must have exactly 1 argument")
                    print(args[0])
                elif name == "enter":
                    if argc != 1:
                        raise Exception("enter() must have exactly 1 argument")
                    prompt = str(args[0])
                    user_input = input(prompt)
                    self.stack.append(user_input)
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
                else:
                    raise Exception(f"Unknown builtin: {name}")

                # write returns nothing; enter pushes a string
                self.ip += 1

            elif opcode == "CALL_FUNC":
                name, argc = arg

                if name not in self.functions:
                    raise Exception(f"Unknown function: {name}")

                meta = self.functions[name]
                entry = meta.get("entry")
                if entry is None:
                    raise Exception(f"Unknown function: {name}")

                param_names = meta.get("params", [])
                expected = len(param_names)
                if argc != expected:
                    raise Exception(f"{name}() expects {expected} arguments, got {argc}")

                args = []
                for _ in range(argc):
                    args.append(self.pop())
                args.reverse()

                if len(self.call_stack) >= self.MAX_CALL_DEPTH:
                    raise Exception(f"Max call depth exceeded ({self.MAX_CALL_DEPTH})")

                # save caller state
                self.call_stack.append((self.ip + 1, self.env))

                # create new local env with parameters
                local_env = {}
                for i, pname in enumerate(param_names):
                    local_env[pname] = args[i]

                self.env = local_env
                self.check_ip(entry, "call")
                self.ip = entry

            elif opcode == "RETURN":
                ret = self.pop() if self.stack else None

                if not self.call_stack:
                    raise Exception("return used outside of a function")

                return_ip, caller_env = self.call_stack.pop()
                self.env = caller_env
                self.stack.append(ret)
                self.ip = return_ip

            elif opcode == "POP":
                self.pop()
                self.ip += 1

            elif opcode == "HALT":
                break

            else:
                raise Exception(f"Unknown opcode: {opcode}")
