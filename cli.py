import sys

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
    elif t == "Literal":
        d["value"] = node.value
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


def main():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python cli.py parse <file.fallen>")
        print("  python cli.py build <file.fallen>")
        print("  python cli.py run <file.fallen>")
        sys.exit(1)

    cmd = sys.argv[1]
    path = sys.argv[2]

    if cmd == "parse":
        cmd_parse(path)
    elif cmd == "build":
        cmd_build(path)
    elif cmd == "run":
        cmd_run(path)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

    
def cmd_run(path):
    vm = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()

        lexer = Lexer(code)
        parser = Parser(lexer)
        program = parser.parse()

        compiler = Compiler()
        bc = compiler.compile(program)

        vm = VM(bc)
        vm.run()
    except Exception as e:
        # If the VM was created, include instruction pointer.
        if vm is not None:
            print(f"Runtime error at ip={vm.ip:04d}: {e}")
        else:
            print(f"Runtime error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
