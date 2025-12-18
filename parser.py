from ast_nodes import (
    Program, VarAssign, Literal, Var, Binary, Unary, Call, Block, If, While, Stop, Continue, FuncDef, Return,
    ListLiteral, ListAccess, SetListItem, AddListItem, RemoveListItem, For,
    Match, DictLiteral, IndexAccess
)

class Parser:
    def __init__(self, lexer):
        self.lexer = lexer
        self.current_token = self.lexer.get_next_token()
        self.function_depth = 0
        self.block_depth = 0

    # move to next token, but only if it matches what we expect
    def eat(self, token_type):
        if self.current_token.type == token_type:
            self.current_token = self.lexer.get_next_token()
        else:
            tok = self.current_token
            raise Exception(f"Expected {token_type}, got {tok.type} at line {tok.line}, col {tok.column}")

    def error_here(self, message):
        tok = self.current_token
        raise Exception(f"{message} at line {tok.line}, col {tok.column}")

    def eat_ident_value(self, expected_value):
        if self.current_token.type != "IDENT" or self.current_token.value != expected_value:
            tok = self.current_token
            got = tok.value if tok.type == "IDENT" else tok.type
            raise Exception(f"Expected '{expected_value}', got {got} at line {tok.line}, col {tok.column}")
        self.eat("IDENT")

    # ignore extra NEWLINEs so formatting can be flexible
    def skip_newlines(self):
        while self.current_token.type == "NEWLINE":
            self.eat("NEWLINE")

    # ---------- TOP LEVEL ----------
    def parse(self):
        statements = []
        self.skip_newlines()

        while self.current_token.type != "EOF":
            stmt = self.statement()
            statements.append(stmt)
            self.skip_newlines()

        return Program(statements)

    # ---------- STATEMENTS ----------
    def statement(self):
        # function definition (v1: only allowed at top-level)
        if self.current_token.type == "FUNC":
            if self.block_depth != 0:
                raise Exception("func definitions are only allowed at top level")
            return self.func_def()

        # return statement (only valid inside a function)
        if self.current_token.type == "RETURN":
            if self.function_depth == 0:
                raise Exception("return used outside of a function")
            return self.return_statement()

        # if statement
        if self.current_token.type == "IF":
            return self.if_statement()
        if self.current_token.type == "ELIF":
            self.error_here("elif used without a preceding if")
        if self.current_token.type == "MATCH":
            return self.match_statement()
        if self.current_token.type == "WHILE":
            return self.while_statement()

        if self.current_token.type == "FOR":
            return self.for_statement()

        # soft-keyword list operations at statement-start
        if self.current_token.type == "IDENT" and self.current_token.value == "set":
            return self.set_statement()

        if self.current_token.type == "IDENT" and self.current_token.value == "add":
            return self.add_statement()

        if self.current_token.type == "IDENT" and self.current_token.value == "remove":
            return self.remove_statement()

        if self.current_token.type == "IDENT" and self.current_token.value == "call":
            # statement sugar: call <list>(<index>) prints the value
            self.eat_ident_value("call")
            expr = self.call_index_expr_from_ident()
            return Call("write", [expr])


        # WRITE keyword call
        if self.current_token.type == "WRITE":
            call = self.call_statement()
            return call

        # otherwise it must start with an identifier (assignment or function call)
        if self.current_token.type == "IDENT":
            # look ahead: could be assignment (TYPE_*) or a normal call like foo(...)
            return self.ident_start_statement()
        if self.current_token.type == "STOP":
            self.eat("STOP")
            return Stop()

        if self.current_token.type == "CONTINUE":
            self.eat("CONTINUE")
            return Continue()

        raise Exception(f"Unexpected token in statement: {self.current_token.type}")

    def for_statement(self):
        self.eat("FOR")

        if self.current_token.type != "IDENT":
            self.error_here("Expected loop variable name after for")
        var_name = self.current_token.value
        self.eat("IDENT")

        self.eat("IN")
        iterable_expr = self.expr()
        body = self.block()
        return For(var_name, iterable_expr, body)

    def set_statement(self):
        self.eat_ident_value("set")
        if self.current_token.type != "IDENT":
            self.error_here("Expected list name after set")
        name = self.current_token.value
        self.eat("IDENT")

        self.eat("LPAREN")
        index_expr = self.expr()
        self.eat("RPAREN")

        self.eat_ident_value("to")

        self.eat("LPAREN")
        value_expr = self.expr()
        self.eat("RPAREN")
        return SetListItem(name, index_expr, value_expr)

    def add_statement(self):
        self.eat_ident_value("add")
        if self.current_token.type != "IDENT":
            self.error_here("Expected list name after add")
        name = self.current_token.value
        self.eat("IDENT")

        self.eat("LPAREN")
        value_expr = self.expr()
        self.eat("RPAREN")
        return AddListItem(name, value_expr)

    def remove_statement(self):
        self.eat_ident_value("remove")
        if self.current_token.type != "IDENT":
            self.error_here("Expected list name after remove")
        name = self.current_token.value
        self.eat("IDENT")
        self.eat("LPAREN")
        index_expr = self.expr()
        self.eat("RPAREN")
        return RemoveListItem(name, index_expr)

    def match_statement(self):
        # match <expr> { <literal> { ... } ... else { ... } }
        self.eat("MATCH")
        expr = self.expr()

        self.eat("LBRACE")
        self.skip_newlines()

        cases = []
        else_block = None

        while self.current_token.type != "RBRACE":
            if self.current_token.type == "ELSE":
                if else_block is not None:
                    self.error_here("match else already defined")
                self.eat("ELSE")
                else_block = self.block()
                self.skip_newlines()
                if self.current_token.type != "RBRACE":
                    self.error_here("match else must be last")
                break

            lit = self.match_case_literal()
            blk = self.block()
            cases.append((lit.value, blk))
            self.skip_newlines()

        self.eat("RBRACE")
        return Match(expr, cases, else_block)

    def match_case_literal(self):
        tok = self.current_token
        if tok.type == "NUMBER":
            self.eat("NUMBER")
            return Literal(tok.value)
        if tok.type == "STRING":
            self.eat("STRING")
            return Literal(tok.value)
        if tok.type == "BOOL":
            self.eat("BOOL")
            return Literal(tok.value)
        self.error_here("match case must be a literal")
    
    def while_statement(self):
        self.eat("WHILE")
        condition = self.expr()
        body = self.block()
        return While(condition, body)

    def ident_start_statement(self):
        # we need to read the name first
        name_token = self.current_token
        self.eat("IDENT")

        # typed assignment:  name TYPE_* value
        if self.current_token.type in ("TYPE_STRING", "TYPE_INT", "TYPE_FLOAT", "TYPE_BOOL", "TYPE_LIST", "TYPE_DICT"):
            type_token = self.current_token
            self.eat(type_token.type)  # consume TYPE_*

            value_expr = self.expr()  # parse right side
            var_type = self.type_token_to_short(type_token.type)

            return VarAssign(name_token.value, var_type, value_expr)

        # function call: name(...)
        if self.current_token.type == "LPAREN":
            return self.finish_call(name_token.value)

        raise Exception("After a name, expected a type marker (=s/=i/=f/=b/=l/=d) or '('")

    def call_statement(self):
        # WRITE is treated like a keyword, but we compile it like a function call
        self.eat("WRITE")
        return self.finish_call("write")

    def finish_call(self, func_name):
        self.eat("LPAREN")

        args = []
        if self.current_token.type != "RPAREN":
            args.append(self.expr())
            while self.current_token.type == "COMMA":
                self.eat("COMMA")
                args.append(self.expr())

        self.eat("RPAREN")
        return Call(func_name, args)

    def if_statement(self):
        # Grammar:
        #   IF expr block (ELIF expr block)* (ELSE block)?
        # Elif chains are represented as nested If nodes in else_block.

        self.eat("IF")
        condition = self.expr()
        then_block = self.block()

        root = If(condition, then_block, None)
        current = root

        # elif/else can be on same line or next line
        self.skip_newlines()

        while self.current_token.type == "ELIF":
            self.eat("ELIF")
            elif_cond = self.expr()
            elif_block = self.block()

            nested = If(elif_cond, elif_block, None)
            current.else_block = nested
            current = nested

            self.skip_newlines()

        if self.current_token.type == "ELSE":
            self.eat("ELSE")
            current.else_block = self.block()

        return root

    def block(self):
        self.eat("LBRACE")
        self.block_depth += 1
        self.skip_newlines()

        statements = []
        while self.current_token.type != "RBRACE":
            statements.append(self.statement())
            self.skip_newlines()

        self.eat("RBRACE")
        self.block_depth -= 1
        return Block(statements)

    def func_def(self):
        self.eat("FUNC")
        if self.current_token.type != "IDENT":
            raise Exception("Expected function name after func")

        name = self.current_token.value
        self.eat("IDENT")
        self.eat("LPAREN")

        params = []
        if self.current_token.type != "RPAREN":
            params.append(self.param())
            while self.current_token.type == "COMMA":
                self.eat("COMMA")
                params.append(self.param())

        self.eat("RPAREN")

        self.function_depth += 1
        body = self.block()
        self.function_depth -= 1

        return FuncDef(name, params, body)

    def param(self):
        if self.current_token.type != "IDENT":
            raise Exception("Expected parameter name")

        param_name = self.current_token.value
        self.eat("IDENT")

        if self.current_token.type not in ("TYPE_STRING", "TYPE_INT", "TYPE_FLOAT", "TYPE_BOOL", "TYPE_LIST", "TYPE_DICT"):
            raise Exception("Expected parameter type marker (=s/=i/=f/=b/=l/=d)")

        type_token = self.current_token
        self.eat(type_token.type)

        return (param_name, self.type_token_to_short(type_token.type))

    def return_statement(self):
        self.eat("RETURN")
        expr = self.expr()
        return Return(expr)

    # ---------- EXPRESSIONS (math + comparisons) ----------
    # expr -> or_expr
    def expr(self):
        return self.or_expr()

    # or_expr -> and_expr (OR and_expr)*
    def or_expr(self):
        node = self.and_expr()
        while self.current_token.type == "OR":
            self.eat("OR")
            right = self.and_expr()
            node = Binary(node, "or", right)
        return node

    # and_expr -> not_expr (AND not_expr)*
    def and_expr(self):
        node = self.not_expr()
        while self.current_token.type == "AND":
            self.eat("AND")
            right = self.not_expr()
            node = Binary(node, "and", right)
        return node

    # not_expr -> NOT not_expr | comparison
    def not_expr(self):
        if self.current_token.type == "NOT":
            self.eat("NOT")
            return Unary("not", self.not_expr())
        return self.comparison()

    # comparison -> term ((==|!=|<|<=|>|>=) term)*
    def comparison(self):
        node = self.term()

        while self.current_token.type in (
            "EQEQ", "NOTEQ", "LT", "LTE", "GT", "GTE"
        ):
            op_token = self.current_token
            self.eat(op_token.type)
            right = self.term()
            node = Binary(node, self.op_token_to_text(op_token.type), right)

        return node

    # term -> factor ((+|-) factor)*
    def term(self):
        node = self.factor()

        while self.current_token.type in ("PLUS", "MINUS"):
            op_token = self.current_token
            self.eat(op_token.type)
            right = self.factor()
            node = Binary(node, self.op_token_to_text(op_token.type), right)

        return node

    # factor -> unary ((*|/) unary)*
    def factor(self):
        node = self.unary()

        while self.current_token.type in ("STAR", "SLASH"):
            op_token = self.current_token
            self.eat(op_token.type)
            right = self.unary()
            node = Binary(node, self.op_token_to_text(op_token.type), right)

        return node

    # unary -> (- unary) | primary
    def unary(self):
        if self.current_token.type == "MINUS":
            self.eat("MINUS")
            # represent -x as (0 - x)
            return Binary(Literal(0), "-", self.unary())
        return self.primary()

    # primary -> NUMBER | STRING | BOOL | IDENT | list_literal | (expr)
    def primary(self):
        tok = self.current_token

        if tok.type == "NUMBER":
            self.eat("NUMBER")
            return Literal(tok.value)

        if tok.type == "STRING":
            self.eat("STRING")
            return Literal(tok.value)

        if tok.type == "BOOL":
            self.eat("BOOL")
            return Literal(tok.value)

        if tok.type == "IDENT":
            name = tok.value
            self.eat("IDENT")

            # list access expression: call <name> or call <name>(<index>)
            # If a user defines a function named call, call(...) still parses as a normal call.
            if name == "call" and self.current_token.type == "IDENT":
                return self.call_index_expr_from_ident()

            # function call like foo(...)
            if self.current_token.type == "LPAREN":
                return self.finish_call(name)

            return Var(name)

        if tok.type == "WRITE":
            # allow write(...) inside expressions too (optional, but nice)
            return self.call_statement()

        if tok.type == "LBRACKET":
            return self.list_literal()

        if tok.type == "LBRACE":
            return self.dict_literal()

        if tok.type == "LPAREN":
            self.eat("LPAREN")
            node = self.expr()
            self.eat("RPAREN")
            return node

        raise Exception(f"Unexpected token in expression: {tok.type} at line {tok.line}, col {tok.column}")

    def list_literal(self):
        self.eat("LBRACKET")
        items = []
        if self.current_token.type != "RBRACKET":
            items.append(self.expr())
            while self.current_token.type == "COMMA":
                self.eat("COMMA")
                items.append(self.expr())
        self.eat("RBRACKET")
        return ListLiteral(items)

    def call_index_expr_from_ident(self):
        # Assumes the leading 'call' IDENT has already been consumed.
        if self.current_token.type != "IDENT":
            self.error_here("Expected list name after call")
        name = self.current_token.value
        self.eat("IDENT")

        if self.current_token.type == "LPAREN":
            self.eat("LPAREN")
            index_expr = self.expr()
            self.eat("RPAREN")
            return IndexAccess(name, index_expr)

        return IndexAccess(name, None)

    def dict_literal(self):
        # Dict literal: { "k": expr, "k2": expr }
        # Keys must be string literals for v1.
        self.eat("LBRACE")
        pairs = []

        if self.current_token.type != "RBRACE":
            while True:
                if self.current_token.type != "STRING":
                    self.error_here("dict key must be a string literal")
                key_tok = self.current_token
                self.eat("STRING")
                self.eat("COLON")
                value_expr = self.expr()
                pairs.append((Literal(key_tok.value), value_expr))

                if self.current_token.type == "COMMA":
                    self.eat("COMMA")
                    continue
                break

        self.eat("RBRACE")
        return DictLiteral(pairs)
    # ---------- HELPERS ----------
    def type_token_to_short(self, type_token):
        mapping = {
            "TYPE_STRING": "s",
            "TYPE_INT": "i",
            "TYPE_FLOAT": "f",
            "TYPE_BOOL": "b",
            "TYPE_LIST": "l",
            "TYPE_DICT": "d",
        }
        return mapping[type_token]

    def op_token_to_text(self, op_type):
        mapping = {
            "PLUS": "+",
            "MINUS": "-",
            "STAR": "*",
            "SLASH": "/",
            "EQEQ": "==",
            "NOTEQ": "!=",
            "LT": "<",
            "LTE": "<=",
            "GT": ">",
            "GTE": ">=",
        }
        return mapping[op_type]


