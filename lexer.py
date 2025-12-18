class Token:
    def __init__(self, type, value=None):
        self.type = type
        self.value = value

    def __repr__(self):
        if self.value is not None:
            return f"{self.type}({self.value})"
        return f"{self.type}"


class Lexer:
    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.current_char = text[0] if text else None

    def advance(self):
        self.pos += 1
        if self.pos >= len(self.text):
            self.current_char = None
        else:
            self.current_char = self.text[self.pos]

    def peek(self):
        nxt = self.pos + 1
        if nxt >= len(self.text):
            return None
        return self.text[nxt]

    # IMPORTANT: skip spaces/tabs only (NOT newlines)
    def skip_whitespace(self):
        while self.current_char and self.current_char in " \t\r":
            self.advance()

    def skip_comment(self):
        while self.current_char and self.current_char != "\n":
            self.advance()

    def read_identifier(self):
        result = ""
        while self.current_char and (self.current_char.isalnum() or self.current_char == "_"):
            result += self.current_char
            self.advance()
        if result == "while":
            return Token("WHILE")
        if result == "if":
            return Token("IF")
        if result == "else":
            return Token("ELSE")
        if result == "and":
            return Token("AND")
        if result == "or":
            return Token("OR")
        if result == "not":
            return Token("NOT")
        if result == "func":
            return Token("FUNC")
        if result == "return":
            return Token("RETURN")
        if result == "write":
            return Token("WRITE")
        if result == "true":
            return Token("BOOL", True)
        if result == "false":
            return Token("BOOL", False)
        if result == "stop":
            return Token("STOP")
        if result == "continue":
            return Token("CONTINUE")

        return Token("IDENT", result)

    def read_number(self):
        result = ""
        has_dot = False

        while self.current_char and (self.current_char.isdigit() or self.current_char == "."):
            if self.current_char == ".":
                if has_dot:
                    break
                has_dot = True
            result += self.current_char
            self.advance()

        if has_dot:
            return Token("NUMBER", float(result))
        return Token("NUMBER", int(result))

    def read_string(self):
        quote = self.current_char  # ' or "
        self.advance()  # skip opening quote
        result = ""

        while self.current_char and self.current_char != quote:
            result += self.current_char
            self.advance()

        if self.current_char != quote:
            raise Exception("Unclosed string")

        self.advance()  # skip closing quote
        return Token("STRING", result)

    def get_next_token(self):
        while self.current_char:

            # NEWLINE is a real token (parser needs it)
            if self.current_char == "\n":
                self.advance()
                return Token("NEWLINE")

            # spaces/tabs
            if self.current_char in " \t\r":
                self.skip_whitespace()
                continue

            # comments
            if self.current_char == "#":
                self.skip_comment()
                continue

            # identifiers / keywords
            if self.current_char.isalpha() or self.current_char == "_":
                return self.read_identifier()

            # numbers
            if self.current_char.isdigit():
                return self.read_number()

            # strings
            if self.current_char in "\"'":
                return self.read_string()

            # typed assignment markers: =s =i =f =b
            if self.current_char == "=":
                # check == first
                if self.peek() == "=":
                    self.advance()
                    self.advance()
                    return Token("EQEQ")

                # otherwise typed assignment like =s
                self.advance()  # consume '='
                if self.current_char == "s":
                    self.advance()
                    return Token("TYPE_STRING")
                if self.current_char == "i":
                    self.advance()
                    return Token("TYPE_INT")
                if self.current_char == "f":
                    self.advance()
                    return Token("TYPE_FLOAT")
                if self.current_char == "b":
                    self.advance()
                    return Token("TYPE_BOOL")

                raise Exception("Expected type after '=' (use =s, =i, =f, =b)")

            # !=
            if self.current_char == "!" and self.peek() == "=":
                self.advance()
                self.advance()
                return Token("NOTEQ")

            # <=, <
            if self.current_char == "<":
                if self.peek() == "=":
                    self.advance()
                    self.advance()
                    return Token("LTE")
                self.advance()
                return Token("LT")

            # >=, >
            if self.current_char == ">":
                if self.peek() == "=":
                    self.advance()
                    self.advance()
                    return Token("GTE")
                self.advance()
                return Token("GT")

            # math
            if self.current_char == "+":
                self.advance()
                return Token("PLUS")
            if self.current_char == "-":
                self.advance()
                return Token("MINUS")
            if self.current_char == "*":
                self.advance()
                return Token("STAR")
            if self.current_char == "/":
                self.advance()
                return Token("SLASH")

            # punctuation
            if self.current_char == ",":
                self.advance()
                return Token("COMMA")

            if self.current_char == "(":
                self.advance()
                return Token("LPAREN")
            if self.current_char == ")":
                self.advance()
                return Token("RPAREN")
            if self.current_char == "{":
                self.advance()
                return Token("LBRACE")
            if self.current_char == "}":
                self.advance()
                return Token("RBRACE")

            raise Exception(f"Unknown character: {self.current_char}")

        return Token("EOF")
