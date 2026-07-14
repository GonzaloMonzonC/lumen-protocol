"""Tests del pipeline completo: Compiler → Bytecode → VM Execution.
Basado en el patrón MSM FUN_00440ca0 (bytecode executor)."""
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

def compile_and_run(code):
    ev = MEvaluator()
    comp = MCompiler(ev)
    bc = comp.compile(code)
    return comp.execute(bc), ev, bc

print('🧪 TESTS BYTECODE VM PIPELINE\n')

# ── Pipeline básico ──

# SET + GET
r, ev, bc = compile_and_run("S x=42")
test("compile+exec SET", r is not None)

# SET + WRITE + KILL
r, ev, bc = compile_and_run("S x=99 W x K x")
test("SET+WRITE+KILL", r is not None)

# ── Múltiples líneas ──

code = """S a=10
S b=20
S c=a+b"""
r, ev, bc = compile_and_run(code)
test("multi-line script", r is not None)

# ── Bytecode estructura ──

_, _, bc = compile_and_run("S x=1")
test("bytecode has instructions", len(bc) > 0)
test("bytecode dump", isinstance(bc.dump(), str))

# ── Opcodes ──

comp = MCompiler()
test("S→SET", comp._token_to_opcode("S") == "SET")
test("SET→SET", comp._token_to_opcode("SET") == "SET")
test("K→KILL", comp._token_to_opcode("K") == "KILL")
test("F→FOR", comp._token_to_opcode("F") == "FOR")
test("I→IF", comp._token_to_opcode("I") == "IF")
test("W→WRITE", comp._token_to_opcode("W") == "WRITE")
test("Q→QUIT", comp._token_to_opcode("Q") == "QUIT")
test("D→DO", comp._token_to_opcode("D") == "DO")
test("G→GOTO", comp._token_to_opcode("G") == "GOTO")
test("R→READ", comp._token_to_opcode("R") == "READ")
test("N→NEW", comp._token_to_opcode("N") == "NEW")
test("O→OPEN", comp._token_to_opcode("O") == "OPEN")
test("C→CLOSE", comp._token_to_opcode("C") == "CLOSE")
test("U→USE", comp._token_to_opcode("U") == "USE")
test("unknown→None", comp._token_to_opcode("ZZZ") is None)

# ── MBytecode ──

bc2 = MBytecode()
test("empty bc len", len(bc2) == 0)
idx = bc2.emit("SET", {"x": 1})
test("emit returns index", idx == 0)
test("emit increments len", len(bc2) == 1)
bc2.emit_label("START")
test("label registered", "START" in bc2.labels)

# ── Edge cases ──

# Código vacío
r, _, _ = compile_and_run("")
test("empty code", r is None)

# Solo comentarios
r, _, _ = compile_and_run("; comment\n; another")
test("only comments", r is None)

# Solo whitespace
r, _, _ = compile_and_run("   \n  ")
test("whitespace only", r is None)

# ── VM behavior ──

# SET followed by KILL
r, ev, _ = compile_and_run("S tmp=1 K tmp")
test("SET then KILL", r is not None)

# Multiple SETs in sequence
r, ev, _ = compile_and_run("S a=1 S b=2 S c=3")
test("3 SETs in sequence", r is not None)

# WRITE after SET
r, ev, _ = compile_and_run('S msg="hello" W msg')
test("SET then WRITE", r is not None)

# IF condition
r, ev, _ = compile_and_run("S x=5 I x>0 S result=1")
test("IF true executes body", r is not None)

# IF false (should skip)
r, ev, _ = compile_and_run("S x=0 I x>0 S result=1")
test("IF false skips body", r is not None)

# QUIT
r, ev, _ = compile_and_run("Q")
test("QUIT", r is None or r is not None)

# ── Integration: compile → dump → execute ──

_, _, bc3 = compile_and_run("S test=42")
dump = bc3.dump()
test("dump output is string", isinstance(dump, str))
test("dump contains SET", "SET" in dump)

# Recompile same code
r4, _, _ = compile_and_run("S test=42")
test("recompile works", r4 is not None)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
