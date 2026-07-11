"""Tests M-Light Compiler (MSM code_gen pattern)."""
import sys, os
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
from m_light import MEvaluator
sys.path.insert(0, os.path.dirname(__file__))
from m_light_compiler import *

p = f = 0
def test(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS M-Light Compiler\n')

ev = MEvaluator()
comp = MCompiler(ev)

# Compile simple
bc = comp.compile("S x=42")
test("compile returns bytecode", isinstance(bc, MBytecode))
test("has instructions", len(bc) > 0)

# Execute
ev2 = MEvaluator()
comp2 = MCompiler(ev2)
bc2 = comp2.compile("S x=42 W x")
r = comp2.execute(bc2)
test("execute returns result", r is not None)

# Multiple commands
ev3 = MEvaluator()
comp3 = MCompiler(ev3)
bc3 = comp3.compile("S a=1 S b=2 S c=a+b")
r3 = comp3.execute(bc3)
test("multi command", r3 is not None)

# WRITE
ev4 = MEvaluator()
comp4 = MCompiler(ev4)
bc4 = comp4.compile('W "hello"')
r4 = comp4.execute(bc4)
test("write string", r4 is not None)

# Empty code
bc5 = comp.compile("")
test("empty code", len(bc5) == 0)

# Comment
bc6 = comp.compile("; comment")
test("comment line", len(bc6) == 0)

# Token to opcode
test("S→SET", comp._token_to_opcode("S") == OP_SET)
test("K→KILL", comp._token_to_opcode("K") == OP_KILL)
test("F→FOR", comp._token_to_opcode("F") == OP_FOR)
test("unknown→None", comp._token_to_opcode("ZZZ") is None)

# Bytecode dump
bc7 = comp.compile("S x=1")
dump = bc7.dump()
test("dump contains opcode", "SET" in dump)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
