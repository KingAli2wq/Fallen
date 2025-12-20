from bytecode import BytecodeProgram
from ast_nodes import (
    Program, VarAssign, Literal, Var, Binary, Unary, Call, Block, If, While, Stop, Continue, FuncDef, Return,
    Import,
    Export,
    Trace,
    ListLiteral, ListAccess, SetListItem, AddListItem, RemoveListItem, For,
    Match, DictLiteral, IndexAccess,
    CompareChain,
    NamedArg,
)


class Compiler:
    def __init__(self, source_path: str | None = None):
        self.bc = BytecodeProgram()
        self.loop_stack = []
        self.in_function = 0
        self._tmp_id = 0
        self.source_path = source_path

    def _debug_for(self, node):
        line = getattr(node, "line", None)
        if self.source_path is None and line is None:
            return None
        dbg = {}
        if self.source_path is not None:
            dbg["file"] = self.source_path
        if line is not None:
            dbg["line"] = line
        return dbg

    def emit(self, opcode, arg=None, node=None):
        return self.bc.emit(opcode, arg, debug=self._debug_for(node))

    def compile(self, node):
        # entry point
        if not isinstance(node, Program):
            raise Exception("Compiler expects a Program node at the top")

        # Ensure execution starts at top-level, not inside the first function body.
        main_jump_i = self.emit("JUMP", None, node)

        # Pass 1: collect all function signatures (allow calls before definition).
        for stmt in node.statements:
            if not isinstance(stmt, FuncDef):
                continue

            if stmt.name in self.bc.functions:
                raise Exception(f"Function already defined: {stmt.name}")

            param_names = [pname for (pname, _ptype, _default) in stmt.params]
            defaults = {}
            for pname, _ptype, default_expr in stmt.params:
                if default_expr is None:
                    continue
                if not isinstance(default_expr, Literal):
                    raise Exception(f"Default value for parameter '{pname}' must be a literal")
                defaults[pname] = default_expr.value
            self.bc.functions[stmt.name] = {
                "entry": None,
                "params": param_names,
                "defaults": defaults,
                "return_type": getattr(stmt, "return_type", None),
                "file": self.source_path,
            }

            # module-level symbol tracking
            self.bc.defined_globals.add(stmt.name)

        # Pass 2: compile all function bodies.
        for stmt in node.statements:
            if isinstance(stmt, FuncDef):
                self.compile_funcdef(stmt)

        # Patch main start address.
        main_start = len(self.bc.instructions)
        self.bc.patch(main_jump_i, main_start)

        # Pass 2: compile top-level statements (skip FuncDef).
        for stmt in node.statements:
            if isinstance(stmt, FuncDef):
                continue
            self.compile_stmt(stmt)

        # Validate explicit exports (v0.1: only allow exporting module-defined symbols).
        if self.bc.exports:
            for name in self.bc.exports:
                if name not in self.bc.defined_globals:
                    raise Exception(f"exported name not defined in module: {name}")

        self.emit("HALT", node=node)
        return self.bc

    # -------- statements --------
    def compile_stmt(self, node):
        if isinstance(node, Import):
            k = self.bc.add_const(node.path_literal)
            self.emit("LOAD_CONST", k, node)
            self.emit("IMPORT", getattr(node, "alias", None), node=node)
            return

        if isinstance(node, Export):
            # No runtime behavior; metadata only.
            if self.in_function != 0:
                raise Exception("export is only allowed at top level")
            self.bc.exports.add(node.name)
            return

        if isinstance(node, Trace):
            self.emit("SET_TRACE", bool(node.enabled), node)
            return

        if isinstance(node, VarAssign):
            # compile the value then store it
            self.compile_expr(node.value)
            self.emit("STORE_NAME", node.name, node)

            # module-level symbol tracking
            if self.in_function == 0:
                self.bc.defined_globals.add(node.name)
            return

        if isinstance(node, Return):
            if self.in_function == 0:
                raise Exception("return used outside of a function")
            self.compile_return(node)
            return

        if isinstance(node, FuncDef):
            # function bodies are compiled in pass 1
            return
        if isinstance(node, While):
            self.compile_while(node)
            return

        if isinstance(node, Match):
            self.compile_match(node)
            return

        if isinstance(node, For):
            self.compile_for(node)
            return

        if isinstance(node, SetListItem):
            self.compile_set_list_item(node)
            return

        if isinstance(node, AddListItem):
            self.compile_add_list_item(node)
            return

        if isinstance(node, RemoveListItem):
            self.compile_remove_list_item(node)
            return

        if isinstance(node, Call):
            self.compile_call(node)
            # Standalone user-function calls should not leave return values on the stack.
            if node.name != "write":
                self.emit("POP", node=node)
            return

        if isinstance(node, If):
            self.compile_if(node)
            return
        if isinstance(node, Stop):
            self.compile_stop()
            return

        if isinstance(node, Continue):
            self.compile_continue()
            return

        raise Exception(f"Unknown statement node: {node.__class__.__name__}")

    def compile_funcdef(self, node):
        if node.name not in self.bc.functions:
            raise Exception(f"Unknown function (internal): {node.name}")
        if self.bc.functions[node.name].get("entry") is not None:
            raise Exception(f"Function already compiled: {node.name}")

        entry = len(self.bc.instructions)
        self.bc.functions[node.name]["entry"] = entry

        self.in_function += 1
        self.compile_block(node.body)
        self.in_function -= 1

        # Implicit return None if control reaches end of function.
        none_k = self.bc.add_const(None)
        self.emit("LOAD_CONST", none_k, node)
        self.emit("RETURN", node=node)

    def compile_return(self, node):
        self.compile_expr(node.expr)
        self.emit("RETURN", node=node)
    def compile_while(self, node):
        loop_start = len(self.bc.instructions)

        # prepare loop frame
        frame = {
            "start": loop_start,
            "break_jumps": [],
            "continue_jumps": [],
            "continue_target": loop_start,
        }
        self.loop_stack.append(frame)

        # condition
        self.compile_expr(node.condition)
        jmp_end_i = self.emit("JUMP_IF_FALSE", None, node)

        # body
        self.compile_block(node.body)

        # continue jumps go here
        self.emit("JUMP", loop_start, node)

        else_start = len(self.bc.instructions)
        if getattr(node, "else_block", None) is not None:
            self.compile_block(node.else_block)

        loop_end = len(self.bc.instructions)

        # condition-false exits go to else (if present) else end
        self.bc.patch(jmp_end_i, else_start if getattr(node, "else_block", None) is not None else loop_end)

        # patch breaks (stop) to end (skip else)
        for jmp_i in frame["break_jumps"]:
            self.bc.patch(jmp_i, loop_end)

        # patch continue jumps
        for jmp_i in frame["continue_jumps"]:
            self.bc.patch(jmp_i, frame["continue_target"])
        self.loop_stack.pop()

    def compile_for(self, node):
        # Strategy: evaluate iterable once into a temp name, then loop index from 0..amount(iterable)-1.
        # This reuses the loop stack so stop/continue work.

        tmp_iter = self._new_tmp("__for_iter")
        tmp_i = self._new_tmp("__for_i")

        # tmp_iter = <iterable>
        self.compile_expr(node.iterable_expr)
        self.emit("STORE_NAME", tmp_iter, node)

        # tmp_i = 0
        zero_k = self.bc.add_const(0)
        self.emit("LOAD_CONST", zero_k, node)
        self.emit("STORE_NAME", tmp_i, node)

        loop_start = len(self.bc.instructions)

        frame = {
            "start": loop_start,
            "break_jumps": [],
            "continue_jumps": [],
            "continue_target": None,  # patched after we know where increment begins
        }
        self.loop_stack.append(frame)

        # condition: tmp_i < amount(tmp_iter)
        self.emit("LOAD_NAME", tmp_i, node)
        self.emit("LOAD_NAME", tmp_iter, node)
        self.emit("CALL_BUILTIN", ("amount", 1), node)
        self.emit("CMP_LT", node=node)
        jmp_end_i = self.emit("JUMP_IF_FALSE", None, node)

        # loop var = call tmp_iter(tmp_i)
        self.emit("LOAD_NAME", tmp_iter, node)
        self.emit("LOAD_NAME", tmp_i, node)
        self.emit("LIST_GET", node=node)
        self.emit("STORE_NAME", node.var_name, node)

        # body
        self.compile_block(node.body)

        # increment
        increment_pos = len(self.bc.instructions)
        frame["continue_target"] = increment_pos
        one_k = self.bc.add_const(1)
        self.emit("LOAD_NAME", tmp_i, node)
        self.emit("LOAD_CONST", one_k, node)
        self.emit("ADD", node=node)
        self.emit("STORE_NAME", tmp_i, node)

        self.emit("JUMP", loop_start, node)

        else_start = len(self.bc.instructions)
        if getattr(node, "else_block", None) is not None:
            self.compile_block(node.else_block)

        loop_end = len(self.bc.instructions)

        # condition-false exits go to else (if present) else end
        self.bc.patch(jmp_end_i, else_start if getattr(node, "else_block", None) is not None else loop_end)

        # patch breaks (stop) to end (skip else)
        for jmp_i in frame["break_jumps"]:
            self.bc.patch(jmp_i, loop_end)

        for jmp_i in frame["continue_jumps"]:
            self.bc.patch(jmp_i, frame["continue_target"])

        self.loop_stack.pop()

    def compile_set_list_item(self, node):
        # runtime-dispatched (list index int, dict key str)
        self.emit("LOAD_NAME", node.name, node)
        self.compile_expr(node.index_expr)
        self.compile_expr(node.value_expr)
        self.emit("INDEX_SET", node=node)

    def compile_add_list_item(self, node):
        self.emit("LOAD_NAME", node.name, node)
        self.compile_expr(node.value_expr)
        self.emit("LIST_APPEND", node=node)

    def compile_remove_list_item(self, node):
        # runtime-dispatched (list index int, dict key str)
        self.emit("LOAD_NAME", node.name, node)
        self.compile_expr(node.index_expr)
        self.emit("INDEX_REMOVE", node=node)

    def compile_match(self, node):
        # Evaluate match expression once into a temp, then compare against each literal.
        tmp = self._new_tmp("__match_tmp")
        self.compile_expr(node.expr)
        self.emit("STORE_NAME", tmp, node)

        end_jumps = []

        for lit_value, block in node.cases:
            self.emit("LOAD_NAME", tmp, node)
            k = self.bc.add_const(lit_value)
            self.emit("LOAD_CONST", k, node)
            self.emit("CMP_EQ", node=node)
            jmp_next_i = self.emit("JUMP_IF_FALSE", None, node)

            self.compile_block(block)
            end_jumps.append(self.emit("JUMP", None, node))

            next_pos = len(self.bc.instructions)
            self.bc.patch(jmp_next_i, next_pos)

        if node.else_block is not None:
            self.compile_block(node.else_block)

        end_pos = len(self.bc.instructions)
        for jmp_i in end_jumps:
            self.bc.patch(jmp_i, end_pos)


    def compile_block(self, block):
        for stmt in block.statements:
            self.compile_stmt(stmt)

    def compile_if(self, node):
        # 1) compile condition (leaves true/false on stack)
        self.compile_expr(node.condition)

        # 2) jump to else if false (we patch the address later)
        jmp_false_i = self.emit("JUMP_IF_FALSE", None, node)

        # 3) then block
        self.compile_block(node.then_block)

        # 4) jump to end after then block
        jmp_end_i = self.emit("JUMP", None, node)

        # 5) patch false jump to "else start"
        else_start = len(self.bc.instructions)
        self.bc.patch(jmp_false_i, else_start)

        # 6) else block (if present)
        if node.else_block is not None:
            # else_block may be a Block (normal else) or a nested If (elif chain)
            if isinstance(node.else_block, Block):
                self.compile_block(node.else_block)
            else:
                self.compile_stmt(node.else_block)

        # 7) patch end jump to "end"
        end_pos = len(self.bc.instructions)
        self.bc.patch(jmp_end_i, end_pos)

    # -------- expressions --------
    def compile_expr(self, node):
        if isinstance(node, Literal):
            if isinstance(node.value, str) and ("{" in node.value or "}" in node.value):
                k = self.bc.add_const(node.value)
                self.emit("LOAD_CONST", k, node)
                self.emit("FORMAT_STRING", node=node)
                return

            k = self.bc.add_const(node.value)
            self.emit("LOAD_CONST", k, node)
            return

        if isinstance(node, ListLiteral):
            for item in node.items:
                self.compile_expr(item)
            self.emit("BUILD_LIST", len(node.items), node)
            return

        if isinstance(node, DictLiteral):
            for key_node, value_node in node.pairs:
                self.compile_expr(key_node)
                self.compile_expr(value_node)
            self.emit("BUILD_DICT", len(node.pairs), node)
            return

        if isinstance(node, Var):
            self.emit("LOAD_NAME", node.name, node)
            return

        if isinstance(node, ListAccess):
            if node.index_expr is None:
                self.emit("LOAD_NAME", node.name, node)
            else:
                self.emit("LOAD_NAME", node.name, node)
                self.compile_expr(node.index_expr)
                self.emit("LIST_GET", node=node)
            return

        if isinstance(node, IndexAccess):
            if node.key_expr is None:
                self.emit("LOAD_NAME", node.name, node)
            else:
                self.emit("LOAD_NAME", node.name, node)
                self.compile_expr(node.key_expr)
                self.emit("INDEX_GET", node=node)
            return

        if isinstance(node, Binary):
            if node.op == "and":
                # Short-circuit AND:
                #   eval left
                #   DUP
                #   JUMP_IF_FALSE end   (pops dup; leaves original left)
                #   POP                 (discard original left; we know it's True)
                #   eval right          (result)
                # end:
                self.compile_expr(node.left)
                self.emit("DUP", node=node)
                jmp_end_i = self.emit("JUMP_IF_FALSE", None, node)
                self.emit("POP", node=node)
                self.compile_expr(node.right)
                end_pos = len(self.bc.instructions)
                self.bc.patch(jmp_end_i, end_pos)
                return

            if node.op == "or":
                # Short-circuit OR:
                #   eval left
                #   DUP
                #   JUMP_IF_FALSE eval_right (pops dup; leaves original left)
                #   JUMP end                (keep original left)
                # eval_right:
                #   POP                     (discard original left; we know it's False)
                #   eval right
                # end:
                self.compile_expr(node.left)
                self.emit("DUP", node=node)
                jmp_eval_right_i = self.emit("JUMP_IF_FALSE", None, node)
                jmp_end_i = self.emit("JUMP", None, node)

                eval_right_pos = len(self.bc.instructions)
                self.bc.patch(jmp_eval_right_i, eval_right_pos)
                self.emit("POP", node=node)
                self.compile_expr(node.right)

                end_pos = len(self.bc.instructions)
                self.bc.patch(jmp_end_i, end_pos)
                return

            self.compile_expr(node.left)
            self.compile_expr(node.right)
            self.emit(self.binary_op_to_opcode(node.op), node=node)
            return

        if isinstance(node, CompareChain):
            # Evaluate each term once, short-circuit on first false.
            tmp_left = self._new_tmp("__cmp_left")
            tmp_right = self._new_tmp("__cmp_right")

            self.compile_expr(node.first)
            self.emit("STORE_NAME", tmp_left, node)

            end_jumps = []
            for i, op in enumerate(node.ops):
                right_expr = node.rest[i]
                self.compile_expr(right_expr)
                self.emit("STORE_NAME", tmp_right, node)

                self.emit("LOAD_NAME", tmp_left, node)
                self.emit("LOAD_NAME", tmp_right, node)
                self.emit(self.binary_op_to_opcode(op), node=node)

                if i != len(node.ops) - 1:
                    self.emit("DUP", node=node)
                    jmp_end_i = self.emit("JUMP_IF_FALSE", None, node)
                    end_jumps.append(jmp_end_i)
                    self.emit("POP", node=node)

                    # advance tmp_left = tmp_right for next comparison
                    self.emit("LOAD_NAME", tmp_right, node)
                    self.emit("STORE_NAME", tmp_left, node)

            end_pos = len(self.bc.instructions)
            for jmp_i in end_jumps:
                self.bc.patch(jmp_i, end_pos)
            return

        if isinstance(node, Unary):
            if node.op != "not":
                raise Exception(f"Unknown unary operator: {node.op}")
            self.compile_expr(node.expr)
            self.emit("NOT", node=node)
            return

        if isinstance(node, Call):
            self.compile_call(node)
            return

        raise Exception(f"Unknown expression node: {node.__class__.__name__}")

    def compile_call(self, node):
        # compile args first (each pushes a value)
        has_named = any(isinstance(a, NamedArg) for a in node.args)
        arg_names = []
        if has_named:
            # enforce positional-first, then named
            for a in node.args:
                if isinstance(a, NamedArg):
                    self.compile_expr(a.value_expr)
                    arg_names.append(a.name)
                else:
                    self.compile_expr(a)
                    arg_names.append(None)
            # If any named args exist, ensure none occur before a positional in our list
            # (Parser already enforces this, but keep compiler defensive.)
            seen_named = False
            for nm in arg_names:
                if nm is None and seen_named:
                    raise Exception("positional args cannot follow named args")
                if nm is not None:
                    seen_named = True
        else:
            for arg in node.args:
                self.compile_expr(arg)

        # only builtin for now: write(x)
        if node.name == "write":
            if has_named:
                raise Exception("write() does not support named arguments")
            self.emit("CALL_BUILTIN", ("write", len(node.args)), node)
            return

        # builtin: enter(prompt)
        if node.name == "enter":
            if has_named:
                raise Exception("enter() does not support named arguments")
            if len(node.args) != 1:
                raise Exception("enter() must have exactly 1 argument")
            self.emit("CALL_BUILTIN", ("enter", 1), node)
            return

        # builtin: args() -> list of CLI/script arguments
        if node.name == "args":
            if has_named:
                raise Exception("args() does not support named arguments")
            if len(node.args) != 0:
                raise Exception("args() must have exactly 0 arguments")
            self.emit("CALL_BUILTIN", ("args", 0), node)
            return

        # builtins: conversions
        if node.name in (
            "conv_int", "conv_float", "conv_bool",
            "try_conv_int", "try_conv_float", "try_conv_bool",
        ):
            if has_named:
                raise Exception(f"{node.name}() does not support named arguments")
            if len(node.args) != 1:
                raise Exception(f"{node.name}() must have exactly 1 argument")
            self.emit("CALL_BUILTIN", (node.name, 1), node)
            return

        # builtins: lists/strings
        if node.name in ("amount", "del", "upper", "lower"):
            if has_named:
                raise Exception(f"{node.name}() does not support named arguments")
            if len(node.args) != 1:
                raise Exception(f"{node.name}() must have exactly 1 argument")
            self.emit("CALL_BUILTIN", (node.name, 1), node)
            return

        if node.name in ("split", "join"):
            if has_named:
                raise Exception(f"{node.name}() does not support named arguments")
            if len(node.args) != 2:
                raise Exception(f"{node.name}() must have exactly 2 arguments")
            self.emit("CALL_BUILTIN", (node.name, 2), node)
            return

        if node.name in ("replace",):
            if has_named:
                raise Exception(f"{node.name}() does not support named arguments")
            if len(node.args) != 3:
                raise Exception(f"{node.name}() must have exactly 3 arguments")
            self.emit("CALL_BUILTIN", (node.name, 3), node)
            return

        if node.name in ("insert",):
            if has_named:
                raise Exception(f"{node.name}() does not support named arguments")
            if len(node.args) != 3:
                raise Exception(f"{node.name}() must have exactly 3 arguments")
            self.emit("CALL_BUILTIN", (node.name, 3), node)
            return

        # builtins: file I/O
        if node.name in ("save", "append", "change"):
            if has_named:
                raise Exception(f"{node.name}() does not support named arguments")
            if len(node.args) != 2:
                raise Exception(f"{node.name}() must have exactly 2 arguments")
            self.emit("CALL_BUILTIN", (node.name, 2), node)
            return

        if node.name in ("load", "read"):
            if has_named:
                raise Exception(f"{node.name}() does not support named arguments")
            if len(node.args) != 1:
                raise Exception(f"{node.name}() must have exactly 1 argument")
            self.emit("CALL_BUILTIN", (node.name, 1), node)
            return

        # user-defined function (existence checked at runtime by VM)
        if has_named:
            self.emit("CALL_FUNC", (node.name, len(node.args), arg_names), node)
        else:
            self.emit("CALL_FUNC", (node.name, len(node.args)), node)

    def compile_stop(self):
        if not self.loop_stack:
            raise Exception("stop used outside of a loop")

        frame = self.loop_stack[-1]
        jmp_i = self.emit("JUMP", None)
        frame["break_jumps"].append(jmp_i)

    def compile_continue(self):
        if not self.loop_stack:
            raise Exception("continue used outside of a loop")

        frame = self.loop_stack[-1]
        jmp_i = self.emit("JUMP", None)
        frame["continue_jumps"].append(jmp_i)

    def _new_tmp(self, prefix):
        name = f"{prefix}_{self._tmp_id}"
        self._tmp_id += 1
        return name

    def binary_op_to_opcode(self, op):
        mapping = {
            "+": "ADD",
            "-": "SUB",
            "*": "MUL",
            "/": "DIV",
            "==": "CMP_EQ",
            "!=": "CMP_NE",
            "<": "CMP_LT",
            "<=": "CMP_LE",
            ">": "CMP_GT",
            ">=": "CMP_GE",
        }
        if op not in mapping:
            raise Exception(f"Unknown operator: {op}")
        return mapping[op]
    