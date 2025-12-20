import os
import sys
import traceback

from vm import VM
from compiler import Compiler
from lexer import Lexer
from parser import Parser


# Simple AST printer (so you can SEE what the parser built)
def ast_to_dict(node):
    if node is None:
        return None

    t = node.__class__.__name__
    d = {"type": t}

    if t == "Program":
        d["statements"] = [ast_to_dict(s) for s in node.statements]
    elif t == "VarAssign":
        d["name"] = node.name
        d["var_type"] = node.var_type
        d["value"] = ast_to_dict(node.value)
    elif t == "Var":
        d["name"] = node.name
    elif t == "Binary":
        d["op"] = node.op
        d["left"] = ast_to_dict(node.left)
        d["right"] = ast_to_dict(node.right)
    elif t == "Unary":
        d["op"] = node.op
        d["expr"] = ast_to_dict(node.expr)
    elif t == "Call":
        d["name"] = node.name
        d["args"] = [ast_to_dict(a) for a in node.args]
    elif t == "ListLiteral":
        d["items"] = [ast_to_dict(i) for i in node.items]
    elif t == "ListAccess":
        d["name"] = node.name
        d["index"] = ast_to_dict(node.index_expr)
    elif t == "SetListItem":
        d["name"] = node.name
        d["index"] = ast_to_dict(node.index_expr)
        d["value"] = ast_to_dict(node.value_expr)
    elif t == "AddListItem":
        d["name"] = node.name
        d["value"] = ast_to_dict(node.value_expr)
    elif t == "RemoveListItem":
        d["name"] = node.name
        d["index"] = ast_to_dict(node.index_expr)
    elif t == "Block":
        d["statements"] = [ast_to_dict(s) for s in node.statements]
    elif t == "If":
        d["condition"] = ast_to_dict(node.condition)
        d["then_block"] = ast_to_dict(node.then_block)
        d["else_block"] = ast_to_dict(node.else_block)
    elif t == "While":
        d["condition"] = ast_to_dict(node.condition)
        d["body"] = ast_to_dict(node.body)
    elif t == "For":
        d["var_name"] = node.var_name
        d["iterable"] = ast_to_dict(node.iterable_expr)
        d["body"] = ast_to_dict(node.body)
    elif t == "Stop":
        pass
    elif t == "Continue":
        pass
    elif t == "FuncDef":
        d["name"] = node.name
        d["params"] = list(node.params)
        d["body"] = ast_to_dict(node.body)
    elif t == "Return":
        d["expr"] = ast_to_dict(node.expr)
    elif t == "Import":
        d["path"] = node.path_literal
        d["alias"] = getattr(node, "alias", None)

    else:
        d["raw"] = str(node)

    return d


def pretty(obj, indent=0):
    sp = "  " * indent
    if isinstance(obj, dict):
        lines = []
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{sp}{k}:")
                lines.append(pretty(v, indent + 1))
            else:
                lines.append(f"{sp}{k}: {v}")
        return "\n".join(lines)
    if isinstance(obj, list):
        lines = []
        for item in obj:
            lines.append(f"{sp}-")
            lines.append(pretty(item, indent + 1))
        return "\n".join(lines)
    return f"{sp}{obj}"


def cmd_parse(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        lexer = Lexer(code)
        parser = Parser(lexer)
        program = parser.parse()

        tree = ast_to_dict(program)
        print(pretty(tree))
    except Exception as e:
        print(f"Parse error: {e}")
        sys.exit(1)


def cmd_build(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        lexer = Lexer(code)
        parser = Parser(lexer)
        program = parser.parse()

        compiler = Compiler()
        bc = compiler.compile(program)
    except Exception as e:
        print(f"Build error: {e}")
        sys.exit(1)

    print("CONSTS:")
    for i, c in enumerate(bc.consts):
        print(f"  [{i}] {c}")

    if getattr(bc, "functions", None):
        print("\nFUNCTIONS:")
        for name, meta in bc.functions.items():
            print(f"  {name}  entry={meta.get('entry')}  params={meta.get('params')}")

    print("\nINSTRUCTIONS:")
    for i, ins in enumerate(bc.instructions):
        print(f"  {i:04d}  {ins}")


def _count_braces_delta(line: str) -> int:
    # Minimal brace balancer for REPL multiline input.
    # Ignores braces inside "..." or '...' strings (best-effort; no escape handling).
    delta = 0
    in_single = False
    in_double = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "#" and not in_single and not in_double:
            break
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == "{":
                delta += 1
            elif ch == "}":
                delta -= 1
        i += 1
    return delta


def cmd_repl(debug: bool = False):
    # Create an initial empty VM and keep it alive across snippets.
    try:
        lexer = Lexer("")
        parser = Parser(lexer)
        program = parser.parse()
        compiler = Compiler(source_path="<repl>")
        bc = compiler.compile(program)

        vm = VM(bc, base_dir=os.getcwd(), entry_file=None)
    except Exception as e:
        if debug:
            traceback.print_exc()
        else:
            print(f"REPL init error: {e}")
        sys.exit(1)

    print("Fallen REPL. Type :q to quit.")

    buffer_lines = []
    brace_depth = 0
    while True:
        prompt = "fallen> " if not buffer_lines else "...> "
        try:
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            break

        stripped = line.strip()
        if not buffer_lines and stripped in (":q", ":quit", "quit", "exit"):
            break

        # Allow blank lines to submit when not inside a block.
        if not stripped and brace_depth == 0 and not buffer_lines:
            continue

        buffer_lines.append(line)
        brace_depth += _count_braces_delta(line)

        # Wait for block completion if braces aren't balanced yet.
        if brace_depth > 0:
            continue

        source = "\n".join(buffer_lines) + "\n"
        buffer_lines = []
        brace_depth = 0

        try:
            # First, try parsing as a normal program (statements).
            try:
                lexer = Lexer(source)
                parser = Parser(lexer)
                program = parser.parse()
            except Exception as parse_err:
                # If that fails, try parsing as a single expression and auto-print it.
                try:
                    from ast_nodes import Program, Call

                    lexer = Lexer(source)
                    parser = Parser(lexer)
                    expr = parser.expr()
                    parser.skip_newlines()
                    if parser.current_token.type != "EOF":
                        raise Exception("extra tokens")
                    program = Program([Call("write", [expr])])
                except Exception:
                    raise parse_err

            compiler = Compiler(source_path="<repl>")
            bc = compiler.compile(program)

            start_ip, end_ip = vm.link_bytecode(bc)
            saved_env = vm.env
            saved_func = vm.current_function_name
            saved_file = vm.current_file_path
            vm.env = vm.globals
            vm.current_function_name = "<repl>"
            vm.current_file_path = "<repl>"
            try:
                vm.run_range(start_ip, end_ip)
            finally:
                vm.env = saved_env
                vm.current_function_name = saved_func
                vm.current_file_path = saved_file
        except Exception as e:
            if debug:
                traceback.print_exc()
            else:
                print(str(e))


def main():
    debug = False
    if "--debug" in sys.argv:
        debug = True
        sys.argv.remove("--debug")

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python cli.py parse <file.fallen>")
        print("  python cli.py build <file.fallen>")
        print("  python cli.py run <file.fallen>")
        print("  python cli.py repl")
        print("  (optional) --debug to show Python traceback")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "repl":
        if len(sys.argv) != 2:
            print("Usage:")
            print("  python cli.py repl")
            sys.exit(1)
        cmd_repl(debug=debug)
        return

    if len(sys.argv) < 3:
        print("Usage:")
        print("  python cli.py parse <file.fallen>")
        print("  python cli.py build <file.fallen>")
        print("  python cli.py run <file.fallen>")
        print("  python cli.py repl")
        print("  (optional) --debug to show Python traceback")
        sys.exit(1)

    path = sys.argv[2]
    extra = sys.argv[3:]

    if cmd == "parse":
        if extra:
            print("Parse does not accept extra arguments.")
            sys.exit(1)
        cmd_parse(path)
    elif cmd == "build":
        if extra:
            print("Build does not accept extra arguments.")
            sys.exit(1)
        cmd_build(path)
    elif cmd == "run":
        script_args = extra
        if "--" in extra:
            i = extra.index("--")
            script_args = extra[i + 1 :]
        cmd_run(path, debug=debug, argv=script_args)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

    
def cmd_run(path, debug: bool = False, argv=None):
    vm = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        lexer = Lexer(code)
        parser = Parser(lexer)
        program = parser.parse()

        abs_path = os.path.abspath(path)
        compiler = Compiler(source_path=abs_path)
        bc = compiler.compile(program)

        base_dir = os.path.dirname(os.path.abspath(path))
        vm = VM(bc, base_dir=base_dir, entry_file=abs_path, argv=argv)
        vm.run()
    except Exception as e:
        if debug:
            traceback.print_exc()
        else:
            print(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
