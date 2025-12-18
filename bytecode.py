class BytecodeProgram:
    def __init__(self):
        self.consts = []         # constants like "big", 10, 5
        self.instructions = []   # list of (OPCODE, arg)
        self.functions = {}      # name -> {"entry": int, "params": [str, ...]}

    def add_const(self, value):
        # reuse constants if already added
        if value in self.consts:
            return self.consts.index(value)
        self.consts.append(value)
        return len(self.consts) - 1

    def emit(self, opcode, arg=None):
        # returns instruction index (useful for jumps)
        self.instructions.append((opcode, arg))
        return len(self.instructions) - 1

    def patch(self, index, arg):
        opcode, _ = self.instructions[index]
        self.instructions[index] = (opcode, arg)
