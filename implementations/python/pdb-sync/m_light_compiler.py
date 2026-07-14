#!/usr/bin/env python3
"""
m_light_compiler.py — Bytecode compiler para M-Light (MSM code_gen pattern).

MSM: FUN_00492010: tokenize → buffer bytecode → FUN_00440c20 (execute)
PDB: compile(code) → MBytecode → execute(bytecode)

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import re, sys, os
from typing import Any, Optional

OP_SET   = "SET"; OP_KILL  = "KILL"; OP_FOR   = "FOR"
OP_IF    = "IF";  OP_WRITE = "WRITE"; OP_QUIT  = "QUIT"
OP_DO    = "DO";  OP_GOTO  = "GOTO"; OP_READ  = "READ"
OP_NEW   = "NEW"; OP_OPEN  = "OPEN"; OP_CLOSE = "CLOSE"
OP_USE   = "USE"; OP_EXPR  = "EXPR"; OP_LABEL = "LABEL"

class Instruction:
    def __init__(self, opcode, args=None, source=""):
        self.opcode = opcode
        self.args = args or {}
        self.source = source
    def __repr__(self):
        return f"{self.opcode}({self.args})"

class MBytecode:
    def __init__(self):
        self.instructions = []
        self.labels = {}
    def emit(self, opcode, args=None, source=""):
        idx = len(self.instructions)
        self.instructions.append(Instruction(opcode, args, source))
        return idx
    def emit_label(self, name):
        idx = len(self.instructions)
        self.labels[name.upper()] = idx
        self.emit(OP_LABEL, {"name": name})
    def dump(self):
        lines = []
    def __len__(self):
        return len(self.instructions)
    def dump(self):
        lines = []
        for name, idx in sorted(self.labels.items(), key=lambda x: x[1]):
            lines.append(f"LABEL {name} @ {idx}")
        for i, inst in enumerate(self.instructions):
            if inst.opcode != OP_LABEL:
                lines.append(f"  [{i:3d}] {inst.opcode:8s} {inst.args}")
        return "\n".join(lines)

class MCompiler:
    def __init__(self, evaluator=None):
        self.evaluator = evaluator
    
    def compile(self, code):
        bc = MBytecode()
        for line in code.split('\n'):
            line = line.strip()
            if not line or line.startswith(';'):
                continue
            self._compile_line(bc, line)
        return bc
    
    def _compile_line(self, bc, line):
        pos = 0
        while pos < len(line):
            while pos < len(line) and line[pos] == ' ':
                pos += 1
            if pos >= len(line):
                break
            end = pos
            while end < len(line) and line[end] not in (' ', ':', '\t'):
                end += 1
            token = line[pos:end]
            postcond = ""
            if end < len(line) and line[end] == ':':
                ce = end + 1
                while ce < len(line) and line[ce] not in (' ', '\t'):
                    ce += 1
                postcond = line[end:ce]
                end = ce
            pos = end
            while pos < len(line) and line[pos] == ' ':
                pos += 1
            opcode = self._token_to_opcode(token)
            if opcode:
                bc.emit(opcode, {"postcond": postcond, "rest": line[pos:], "token": token})
                break
            else:
                bc.emit(OP_EXPR, {"expr": line[pos:]})
                break
    
    def _token_to_opcode(self, token):
        t = token.upper()
        m = {"S":OP_SET,"SET":OP_SET,"K":OP_KILL,"KILL":OP_KILL,
             "F":OP_FOR,"FOR":OP_FOR,"I":OP_IF,"IF":OP_IF,
             "W":OP_WRITE,"WRITE":OP_WRITE,"Q":OP_QUIT,"QUIT":OP_QUIT,
             "D":OP_DO,"DO":OP_DO,"G":OP_GOTO,"GOTO":OP_GOTO,
             "R":OP_READ,"READ":OP_READ,"N":OP_NEW,"NEW":OP_NEW,
             "O":OP_OPEN,"OPEN":OP_OPEN,"C":OP_CLOSE,"CLOSE":OP_CLOSE,
             "U":OP_USE,"USE":OP_USE}
        return m.get(t)
    
    def execute(self, bc):
        if not self.evaluator:
            raise ValueError("evaluator required")
        ev = self.evaluator
        result = None
        ip = 0
        while 0 <= ip < len(bc.instructions):
            inst = bc.instructions[ip]
            if inst.opcode == OP_LABEL:
                ip += 1; continue
            if inst.args.get("postcond"):
                try:
                    cv = ev.eval_expr(inst.args["postcond"][1:])
                    if not cv: ip += 1; continue
                except: ip += 1; continue
            
            rest = inst.args.get("rest", "")
            h = {"SET":ev._exec_set,"KILL":ev._exec_kill,"FOR":ev._exec_for,
                 "IF":ev._exec_if,"WRITE":ev._exec_write,"DO":ev._exec_do,
                 "GOTO":ev._exec_goto,"READ":ev._exec_read,"NEW":ev._exec_new,
                 "OPEN":ev._exec_open,"CLOSE":ev._exec_close,"USE":ev._exec_use}
            if inst.opcode == OP_QUIT:
                result = ev._exec_quit(rest, inst.args.get("postcond",""))
                ip += 1
            elif inst.opcode == OP_EXPR:
                result = ev.eval_expr(inst.args.get("expr",""))
                ip += 1
            elif inst.opcode in h:
                result = h[inst.opcode](rest, 0)
                ip += 1
            else:
                ip += 1
            if isinstance(result, int) and result < 0:
                break
        return result

if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "S x=42 W x"
    import _paths  # noqa: F401  # sys.path del stack PDB
    from m_light import MEvaluator
    ev = MEvaluator()
    comp = MCompiler(ev)
    print(f"📋 Compiling: {code}\n")
    bc = comp.compile(code)
    print(bc.dump())
    print()
    result = comp.execute(bc)
    print(f"Result: {result}")
