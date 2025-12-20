class ASTNode:
    # Optional source line (1-based). Parser may set this.
    line: int | None = None


class Program(ASTNode):
    def __init__(self, statements):
        self.statements = statements


class VarAssign(ASTNode):
    def __init__(self, name, var_type, value):
        self.name = name          # variable name
        self.var_type = var_type  # s, i, f, b
        self.value = value        # expression


class Literal(ASTNode):
    def __init__(self, value):
        self.value = value


class Var(ASTNode):
    def __init__(self, name):
        self.name = name


class Binary(ASTNode):
    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right


class CompareChain(ASTNode):
    def __init__(self, first, ops, rest):
        # Represents: first (ops[0]) rest[0] (ops[1]) rest[1] ...
        # first: expr, ops: list[str], rest: list[expr]
        self.first = first
        self.ops = ops
        self.rest = rest


class Unary(ASTNode):
    def __init__(self, op, expr):
        self.op = op
        self.expr = expr


class Call(ASTNode):
    def __init__(self, name, args):
        self.name = name
        self.args = args


class NamedArg(ASTNode):
    def __init__(self, name, value_expr):
        self.name = name
        self.value_expr = value_expr


class Block(ASTNode):
    def __init__(self, statements):
        self.statements = statements


class If(ASTNode):
    def __init__(self, condition, then_block, else_block=None):
        self.condition = condition
        self.then_block = then_block
        self.else_block = else_block


class While(ASTNode):
    def __init__(self, condition, body, else_block=None):
        self.condition = condition
        self.body = body
        self.else_block = else_block


class Stop(ASTNode):
    pass


class Continue(ASTNode):
    pass


class FuncDef(ASTNode):
    def __init__(self, name, params, body, return_type=None):
        self.name = name
        self.params = params  # list of (param_name, param_type)
        self.body = body      # Block
        self.return_type = return_type


class Return(ASTNode):
    def __init__(self, expr):
        self.expr = expr


class Import(ASTNode):
    def __init__(self, path_literal, alias: str | None = None):
        self.path_literal = path_literal
        self.alias = alias


class Export(ASTNode):
    def __init__(self, name):
        self.name = name


class Trace(ASTNode):
    def __init__(self, enabled: bool):
        self.enabled = enabled


class ListLiteral(ASTNode):
    def __init__(self, items):
        self.items = items  # list[expr]


class ListAccess(ASTNode):
    def __init__(self, name, index_expr=None):
        self.name = name
        self.index_expr = index_expr  # expr | None


class SetListItem(ASTNode):
    def __init__(self, name, index_expr, value_expr):
        self.name = name
        self.index_expr = index_expr
        self.value_expr = value_expr


class AddListItem(ASTNode):
    def __init__(self, name, value_expr):
        self.name = name
        self.value_expr = value_expr


class RemoveListItem(ASTNode):
    def __init__(self, name, index_expr):
        self.name = name
        self.index_expr = index_expr


class For(ASTNode):
    def __init__(self, var_name, iterable_expr, body, else_block=None):
        self.var_name = var_name
        self.iterable_expr = iterable_expr
        self.body = body
        self.else_block = else_block


class Match(ASTNode):
    def __init__(self, expr, cases, else_block=None):
        self.expr = expr
        self.cases = cases  # list[(literal_value, Block)]
        self.else_block = else_block  # Block | None


class DictLiteral(ASTNode):
    def __init__(self, pairs):
        self.pairs = pairs  # list[(Literal(str), expr)]


class IndexAccess(ASTNode):
    def __init__(self, name, key_expr=None):
        self.name = name
        self.key_expr = key_expr  # expr | None

