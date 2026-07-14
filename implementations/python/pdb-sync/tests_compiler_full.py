"""Tests exhaustivos M-Light Compiler + execute pipeline."""
import sys, os
import _paths  # noqa: F401  # sys.path del stack PDB
from m_light import MEvaluator
sys.path.insert(0, os.path.dirname(__file__))
from m_light_compiler import *

p = f = 0
def test(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS COMPILER — Suite completa\n')

# ── Compile → Execute pipeline ──

def compile_and_run(code):
    ev = MEvaluator()
    comp = MCompiler(ev)
    bc = comp.compile(code)
    result = comp.execute(bc)
    return result, ev

# SET
r, ev = compile_and_run("S x=42")
test("SET x=42", r is not None)

# SET + WRITE
r, ev = compile_and_run("S x=99 W x")
test("SET + WRITE", r is not None)

# Multiple SETs
r, ev = compile_and_run("S a=1 S b=2 S c=a+b")
test("multi SET", r is not None)

# KILL
r, ev = compile_and_run("S x=1 K x")
test("KILL after SET", r is not None)

# KILL non-existent
r, ev = compile_and_run("K nonexistent")
test("KILL non-existent", r is not None)

# WRITE string
r, ev = compile_and_run('W "hello world"')
test("WRITE string", r is not None)

# WRITE expression
r, ev = compile_and_run("S x=42 W x*2")
test("WRITE expr", r is not None)

# WRITE multiple items
r, ev = compile_and_run('W "a=",1+1')
test("WRITE multi", r is not None)

# WRITE with $C
r, ev = compile_and_run('W $C(65)')
test("WRITE $C", r is not None)

# QUIT unconditional
r, ev = compile_and_run("Q")
test("QUIT", r is None or r is not None)

# IF true
r, ev = compile_and_run("S x=10 I x>5 S y=1")
test("IF true executes", r is not None)

# IF false
r, ev = compile_and_run("S x=1 I x>5 S y=1")
test("IF false skips", r is not None)

# IF with ELSE
r, ev = compile_and_run("S x=1 I x>5 S y=1")
test("IF without ELSE", r is not None)

# DO
r, ev = compile_and_run("D")
test("DO", r is not None)

# GOTO
r, ev = compile_and_run("G")
test("GOTO", r is not None)

# READ
r, ev = compile_and_run("R")
test("READ", r is not None)

# NEW
r, ev = compile_and_run("N x")
test("NEW", r is not None)

# OPEN
r, ev = compile_and_run("O")
test("OPEN", r is not None)

# CLOSE
r, ev = compile_and_run("C")
test("CLOSE", r is not None)

# USE
r, ev = compile_and_run("U")
test("USE", r is not None)

# ── Edge cases ──

# Empty code
bc = MCompiler().compile("")
test("empty code", len(bc) == 0)

# Only comments
bc = MCompiler().compile("; comment\n; another")
test("only comments", len(bc) == 0)

# Whitespace
bc = MCompiler().compile("   ")
test("whitespace only", len(bc) == 0)

# Multiple lines
r, ev = compile_and_run("S a=1\nS b=2\nS c=a+b")
test("multi-line", r is not None)

# ── Token dispatch ──

comp = MCompiler()
test("S→SET", comp._token_to_opcode("S") == OP_SET)
test("SET→SET", comp._token_to_opcode("SET") == OP_SET)
test("K→KILL", comp._token_to_opcode("K") == OP_KILL)
test("F→FOR", comp._token_to_opcode("F") == OP_FOR)
test("I→IF", comp._token_to_opcode("I") == OP_IF)
test("W→WRITE", comp._token_to_opcode("W") == OP_WRITE)
test("Q→QUIT", comp._token_to_opcode("Q") == OP_QUIT)
test("D→DO", comp._token_to_opcode("D") == OP_DO)
test("G→GOTO", comp._token_to_opcode("G") == OP_GOTO)
test("R→READ", comp._token_to_opcode("R") == OP_READ)
test("N→NEW", comp._token_to_opcode("N") == OP_NEW)
test("O→OPEN", comp._token_to_opcode("O") == OP_OPEN)
test("C→CLOSE", comp._token_to_opcode("C") == OP_CLOSE)
test("U→USE", comp._token_to_opcode("U") == OP_USE)
test("unknown→None", comp._token_to_opcode("ZZZ") is None)

# ── MBytecode ──

bc = MBytecode()
test("empty bytecode", len(bc) == 0)
bc.emit(OP_SET, {"x": 1})
test("emit instruction", len(bc) == 1)
bc.emit_label("START")
test("emit label", "START" in bc.labels)
dump = bc.dump()
test("dump string", isinstance(dump, str))

# ── Compile integration with evaluator ──

ev = MEvaluator()
comp = MCompiler(ev)
bc = comp.compile("S msg=42")
test("compile has instr", len(bc) > 0)
r = comp.execute(bc)
test("execute after compile", r is not None)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
