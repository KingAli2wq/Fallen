from bytecode import BytecodeProgram
from ast_nodes import (
    Program, VarAssign, Literal, Var, Binary, Unary, Call, Block, If, While, Stop, Continue, FuncDef, Return,
    ListLiteral, ListAccess, SetListItem, AddListItem, RemoveListItem, For,
    Match, DictLiteral, IndexAccess,
)


class Compiler:
    def __init__(self):
        self.bc = BytecodeProgram()
        self.loop_stack = []
        self.in_function = 0
        self._tmp_id = 0

    def compile(self, node):
        # entry point
        if not isinstance(node, Program):
            raise Exception("Compiler expects a Program node at the top")

        # Ensure execution starts at top-level, not inside the first function body.
        main_jump_i = self.bc.emit("JUMP", None)

        # Pass 1: collect all function signatures (allow calls before definition).
        for stmt in node.statements:
            if not isinstance(stmt, FuncDef):
                continue

            if stmt.name in self.bc.functions:
                raise Exception(f"Function already defined: {stmt.name}")

            param_names = [pname for (pname, _ptype) in stmt.params]
            self.bc.functions[stmt.name] = {
                "entry": None,
                "params": param_names,
            }

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

        self.bc.emit("HALT")
        return self.bc

    # -------- statements --------
    def compile_stmt(self, node):
        if isinstance(node, VarAssign):
            # compile the value then store it
            self.compile_expr(node.value)
            self.bc.emit("STORE_NAME", node.name)
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
                self.bc.emit("POP")
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
        self.bc.emit("LOAD_CONST", none_k)
        self.bc.emit("RETURN")

    def compile_return(self, node):
        self.compile_expr(node.expr)
        self.bc.emit("RETURN")
    def compile_while(self, node):
        loop_start = len(self.bc.instructions)

        # prepare loop frame
        frame = {
            "start": loop_start,
            "stop_jumps": [],
            "continue_jumps": [],
            "continue_target": loop_start,
        }
        self.loop_stack.append(frame)

        # condition
        self.compile_expr(node.condition)
        jmp_end_i = self.bc.emit("JUMP_IF_FALSE", None)
        frame["stop_jumps"].append(jmp_end_i)

        # body
        self.compile_block(node.body)

        # continue jumps go here
        self.bc.emit("JUMP", loop_start)

        loop_end = len(self.bc.instructions)

        # patch stop jumps
        for jmp_i in frame["stop_jumps"]:
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
        self.bc.emit("STORE_NAME", tmp_iter)

        # tmp_i = 0
        zero_k = self.bc.add_const(0)
        self.bc.emit("LOAD_CONST", zero_k)
        self.bc.emit("STORE_NAME", tmp_i)

        loop_start = len(self.bc.instructions)

        frame = {
            "start": loop_start,
            "stop_jumps": [],
            "continue_jumps": [],
            "continue_target": None,  # patched after we know where increment begins
        }
        self.loop_stack.append(frame)

        # condition: tmp_i < amount(tmp_iter)
        self.bc.emit("LOAD_NAME", tmp_i)
        self.bc.emit("LOAD_NAME", tmp_iter)
        self.bc.emit("CALL_BUILTIN", ("amount", 1))
        self.bc.emit("CMP_LT")
        jmp_end_i = self.bc.emit("JUMP_IF_FALSE", None)
        frame["stop_jumps"].append(jmp_end_i)

        # loop var = call tmp_iter(tmp_i)
        self.bc.emit("LOAD_NAME", tmp_iter)
        self.bc.emit("LOAD_NAME", tmp_i)
        self.bc.emit("LIST_GET")
        self.bc.emit("STORE_NAME", node.var_name)

        # body
        self.compile_block(node.body)

        # increment
        increment_pos = len(self.bc.instructions)
        frame["continue_target"] = increment_pos
        one_k = self.bc.add_const(1)
        self.bc.emit("LOAD_NAME", tmp_i)
        self.bc.emit("LOAD_CONST", one_k)
        self.bc.emit("ADD")
        self.bc.emit("STORE_NAME", tmp_i)

        self.bc.emit("JUMP", loop_start)

        loop_end = len(self.bc.instructions)

        for jmp_i in frame["stop_jumps"]:
            self.bc.patch(jmp_i, loop_end)

        for jmp_i in frame["continue_jumps"]:
            self.bc.patch(jmp_i, frame["continue_target"])

        self.loop_stack.pop()

    def compile_set_list_item(self, node):
        # runtime-dispatched (list index int, dict key str)
        self.bc.emit("LOAD_NAME", node.name)
        self.compile_expr(node.index_expr)
        self.compile_expr(node.value_expr)
        self.bc.emit("INDEX_SET")

    def compile_add_list_item(self, node):
        self.bc.emit("LOAD_NAME", node.name)
        self.compile_expr(node.value_expr)
        self.bc.emit("LIST_APPEND")

    def compile_remove_list_item(self, node):
        # runtime-dispatched (list index int, dict key str)
        self.bc.emit("LOAD_NAME", node.name)
        self.compile_expr(node.index_expr)
        self.bc.emit("INDEX_REMOVE")

    def compile_match(self, node):
        # Evaluate match expression once into a temp, then compare against each literal.
        tmp = self._new_tmp("__match_tmp")
        self.compile_expr(node.expr)
        self.bc.emit("STORE_NAME", tmp)

        end_jumps = []

        for lit_value, block in node.cases:
            self.bc.emit("LOAD_NAME", tmp)
            k = self.bc.add_const(lit_value)
            self.bc.emit("LOAD_CONST", k)
            self.bc.emit("CMP_EQ")
            jmp_next_i = self.bc.emit("JUMP_IF_FALSE", None)

            self.compile_block(block)
            end_jumps.append(self.bc.emit("JUMP", None))

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
        jmp_false_i = self.bc.emit("JUMP_IF_FALSE", None)

        # 3) then block
        self.compile_block(node.then_block)

        # 4) jump to end after then block
        jmp_end_i = self.bc.emit("JUMP", None)

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
            k = self.bc.add_const(node.value)
            self.bc.emit("LOAD_CONST", k)
            return

        if isinstance(node, ListLiteral):
            for item in node.items:
                self.compile_expr(item)
            self.bc.emit("BUILD_LIST", len(node.items))
            return

        if isinstance(node, DictLiteral):
            for key_node, value_node in node.pairs:
                self.compile_expr(key_node)
                self.compile_expr(value_node)
            self.bc.emit("BUILD_DICT", len(node.pairs))
            return

        if isinstance(node, Var):
            self.bc.emit("LOAD_NAME", node.name)
            return

        if isinstance(node, ListAccess):
            if node.index_expr is None:
                self.bc.emit("LOAD_NAME", node.name)
            else:
                self.bc.emit("LOAD_NAME", node.name)
                self.compile_expr(node.index_expr)
                self.bc.emit("LIST_GET")
            return

        if isinstance(node, IndexAccess):
            if node.key_expr is None:
                self.bc.emit("LOAD_NAME", node.name)
            else:
                self.bc.emit("LOAD_NAME", node.name)
                self.compile_expr(node.key_expr)
                self.bc.emit("INDEX_GET")
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
                self.bc.emit("DUP")
                jmp_end_i = self.bc.emit("JUMP_IF_FALSE", None)
                self.bc.emit("POP")
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
                self.bc.emit("DUP")
                jmp_eval_right_i = self.bc.emit("JUMP_IF_FALSE", None)
                jmp_end_i = self.bc.emit("JUMP", None)

                eval_right_pos = len(self.bc.instructions)
                self.bc.patch(jmp_eval_right_i, eval_right_pos)
                self.bc.emit("POP")
                self.compile_expr(node.right)

                end_pos = len(self.bc.instructions)
                self.bc.patch(jmp_end_i, end_pos)
                return

            self.compile_expr(node.left)
            self.compile_expr(node.right)
            self.bc.emit(self.binary_op_to_opcode(node.op))
            return

        if isinstance(node, Unary):
            if node.op != "not":
                raise Exception(f"Unknown unary operator: {node.op}")
            self.compile_expr(node.expr)
            self.bc.emit("NOT")
            return

        if isinstance(node, Call):
            self.compile_call(node)
            return

        raise Exception(f"Unknown expression node: {node.__class__.__name__}")

    def compile_call(self, node):
        # compile args first (each pushes a value)
        for arg in node.args:
            self.compile_expr(arg)

        # only builtin for now: write(x)
        if node.name == "write":
            self.bc.emit("CALL_BUILTIN", ("write", len(node.args)))
            return

        # builtin: enter(prompt)
        if node.name == "enter":
            if len(node.args) != 1:
                raise Exception("enter() must have exactly 1 argument")
            self.bc.emit("CALL_BUILTIN", ("enter", 1))
            return

        # builtins: conversions
        if node.name in (
            "conv_int", "conv_float", "conv_bool",
            "try_conv_int", "try_conv_float", "try_conv_bool",
        ):
            if len(node.args) != 1:
                raise Exception(f"{node.name}() must have exactly 1 argument")
            self.bc.emit("CALL_BUILTIN", (node.name, 1))
            return

        # builtins: lists/strings
        if node.name in ("amount", "del"):
            if len(node.args) != 1:
                raise Exception(f"{node.name}() must have exactly 1 argument")
            self.bc.emit("CALL_BUILTIN", (node.name, 1))
            return

        # builtins: file I/O
        if node.name in ("save", "append"):
            if len(node.args) != 2:
                raise Exception(f"{node.name}() must have exactly 2 arguments")
            self.bc.emit("CALL_BUILTIN", (node.name, 2))
            return

        if node.name == "load":
            if len(node.args) != 1:
                raise Exception("load() must have exactly 1 argument")
            self.bc.emit("CALL_BUILTIN", ("load", 1))
            return

        # user-defined function (existence checked at runtime by VM)
        self.bc.emit("CALL_FUNC", (node.name, len(node.args)))
    def compile_stop(self):
        if not self.loop_stack:
            raise Exception("stop used outside of a loop")

        frame = self.loop_stack[-1]
        jmp_i = self.bc.emit("JUMP", None)
        frame["stop_jumps"].append(jmp_i)
    def compile_continue(self):
        if not self.loop_stack:
            raise Exception("continue used outside of a loop")

        frame = self.loop_stack[-1]
        jmp_i = self.bc.emit("JUMP", None)
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
    