class Token:
    def __init__(self, type, value=None, line=1, column=1):
        self.type = type
        self.value = value
        self.line = line
        self.column = column

    def __repr__(self):
        if self.value is not None:
            return f"{self.type}({self.value})"
        return f"{self.type}"


class Lexer:
    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.current_char = text[0] if text else None
        self.line = 1
        self.column = 1

    def advance(self):
        # track line/column based on current_char before moving
        if self.current_char == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
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
        start_line, start_col = self.line, self.column
        result = ""
        while self.current_char and (self.current_char.isalnum() or self.current_char == "_"):
            result += self.current_char
            self.advance()
        if result == "while":
            return Token("WHILE", line=start_line, column=start_col)
        if result == "if":
            return Token("IF", line=start_line, column=start_col)
        if result == "elif":
            return Token("ELIF", line=start_line, column=start_col)
        if result == "else":
            return Token("ELSE", line=start_line, column=start_col)
        if result == "match":
            return Token("MATCH", line=start_line, column=start_col)
        if result == "and":
            return Token("AND", line=start_line, column=start_col)
        if result == "or":
            return Token("OR", line=start_line, column=start_col)
        if result == "not":
            return Token("NOT", line=start_line, column=start_col)
        if result == "func":
            return Token("FUNC", line=start_line, column=start_col)
        if result == "return":
            return Token("RETURN", line=start_line, column=start_col)
        if result == "write":
            return Token("WRITE", line=start_line, column=start_col)
        if result == "for":
            return Token("FOR", line=start_line, column=start_col)
        if result == "in":
            return Token("IN", line=start_line, column=start_col)
        if result == "true":
            return Token("BOOL", True, line=start_line, column=start_col)
        if result == "false":
            return Token("BOOL", False, line=start_line, column=start_col)
        if result == "stop":
            return Token("STOP", line=start_line, column=start_col)
        if result == "continue":
            return Token("CONTINUE", line=start_line, column=start_col)

        return Token("IDENT", result, line=start_line, column=start_col)

    def read_number(self):
        start_line, start_col = self.line, self.column
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
            return Token("NUMBER", float(result), line=start_line, column=start_col)
        return Token("NUMBER", int(result), line=start_line, column=start_col)

    def read_string(self):
        start_line, start_col = self.line, self.column
        quote = self.current_char  # ' or "
        self.advance()  # skip opening quote
        result = ""

        while self.current_char and self.current_char != quote:
            if self.current_char == "\\":
                # minimal escape support: \n, \t, \\, \" and \'
                self.advance()  # consume backslash
                if self.current_char is None:
                    break
                esc = self.current_char
                if esc == "n":
                    result += "\n"
                elif esc == "t":
                    result += "\t"
                elif esc == "\\":
                    result += "\\"
                elif esc == quote:
                    result += quote
                elif esc == "\"" and quote == "'":
                    result += "\""
                elif esc == "'" and quote == "\"":
                    result += "'"
                else:
                    # unknown escape: keep literally
                    result += esc
                self.advance()
                continue

            result += self.current_char
            self.advance()

        if self.current_char != quote:
            raise Exception("Unclosed string")

        self.advance()  # skip closing quote
        return Token("STRING", result, line=start_line, column=start_col)

    def get_next_token(self):
        while self.current_char:

            # NEWLINE is a real token (parser needs it)
            if self.current_char == "\n":
                start_line, start_col = self.line, self.column
                self.advance()
                return Token("NEWLINE", line=start_line, column=start_col)

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
                start_line, start_col = self.line, self.column
                # check == first
                if self.peek() == "=":
                    self.advance()
                    self.advance()
                    return Token("EQEQ", line=start_line, column=start_col)

                # otherwise typed assignment like =s
                self.advance()  # consume '='
                if self.current_char == "s":
                    self.advance()
                    return Token("TYPE_STRING", line=start_line, column=start_col)
                if self.current_char == "i":
                    self.advance()
                    return Token("TYPE_INT", line=start_line, column=start_col)
                if self.current_char == "f":
                    self.advance()
                    return Token("TYPE_FLOAT", line=start_line, column=start_col)
                if self.current_char == "b":
                    self.advance()
                    return Token("TYPE_BOOL", line=start_line, column=start_col)
                if self.current_char == "l":
                    self.advance()
                    return Token("TYPE_LIST", line=start_line, column=start_col)
                if self.current_char == "d":
                    self.advance()
                    return Token("TYPE_DICT", line=start_line, column=start_col)

                raise Exception("Expected type after '=' (use =s, =i, =f, =b)")

            # !=
            if self.current_char == "!" and self.peek() == "=":
                start_line, start_col = self.line, self.column
                self.advance()
                self.advance()
                return Token("NOTEQ", line=start_line, column=start_col)

            # <=, <
            if self.current_char == "<":
                start_line, start_col = self.line, self.column
                if self.peek() == "=":
                    self.advance()
                    self.advance()
                    return Token("LTE", line=start_line, column=start_col)
                self.advance()
                return Token("LT", line=start_line, column=start_col)

            # >=, >
            if self.current_char == ">":
                start_line, start_col = self.line, self.column
                if self.peek() == "=":
                    self.advance()
                    self.advance()
                    return Token("GTE", line=start_line, column=start_col)
                self.advance()
                return Token("GT", line=start_line, column=start_col)

            # math
            if self.current_char == "+":
                start_line, start_col = self.line, self.column
                self.advance()
                return Token("PLUS", line=start_line, column=start_col)
            if self.current_char == "-":
                start_line, start_col = self.line, self.column
                self.advance()
                return Token("MINUS", line=start_line, column=start_col)
            if self.current_char == "*":
                start_line, start_col = self.line, self.column
                self.advance()
                return Token("STAR", line=start_line, column=start_col)
            if self.current_char == "/":
                start_line, start_col = self.line, self.column
                self.advance()
                return Token("SLASH", line=start_line, column=start_col)

            # punctuation
            if self.current_char == ",":
                start_line, start_col = self.line, self.column
                self.advance()
                return Token("COMMA", line=start_line, column=start_col)

            if self.current_char == ":":
                start_line, start_col = self.line, self.column
                self.advance()
                return Token("COLON", line=start_line, column=start_col)

            if self.current_char == "(":
                start_line, start_col = self.line, self.column
                self.advance()
                return Token("LPAREN", line=start_line, column=start_col)
            if self.current_char == ")":
                start_line, start_col = self.line, self.column
                self.advance()
                return Token("RPAREN", line=start_line, column=start_col)
            if self.current_char == "{":
                start_line, start_col = self.line, self.column
                self.advance()
                return Token("LBRACE", line=start_line, column=start_col)
            if self.current_char == "}":
                start_line, start_col = self.line, self.column
                self.advance()
                return Token("RBRACE", line=start_line, column=start_col)
            if self.current_char == "[":
                start_line, start_col = self.line, self.column
                self.advance()
                return Token("LBRACKET", line=start_line, column=start_col)
            if self.current_char == "]":
                start_line, start_col = self.line, self.column
                self.advance()
                return Token("RBRACKET", line=start_line, column=start_col)

            raise Exception(f"Unknown character: {self.current_char}")

        return Token("EOF", line=self.line, column=self.column)
