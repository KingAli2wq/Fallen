class BytecodeProgram:
    def __init__(self):
        self.consts = []         # constants like "big", 10, 5
        self.instructions = []   # list of (OPCODE, arg)
        self.debug = []          # list of debug dicts (e.g. {"file": str, "line": int}) aligned with instructions
        self.functions = {}      # name -> {"entry": int, "params": [str, ...]}

        # Module metadata (used by VM import filtering)
        self.defined_globals = set()  # set[str]
        self.exports = set()          # set[str]

    def add_const(self, value):
        # reuse constants if already added
        if value in self.consts:
            return self.consts.index(value)
        self.consts.append(value)
        return len(self.consts) - 1

    def emit(self, opcode, arg=None, debug=None):
        # returns instruction index (useful for jumps)
        self.instructions.append((opcode, arg))
        self.debug.append(debug)
        return len(self.instructions) - 1

    def patch(self, index, arg):
        opcode, _ = self.instructions[index]
        self.instructions[index] = (opcode, arg)
