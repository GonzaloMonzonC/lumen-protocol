"""OBJ-3 Test"""
import sys, os, tempfile
tmpdir = tempfile.mkdtemp()
os.environ['PDB_PATH'] = os.path.join(tmpdir, 't.db')
sys.path.insert(0, os.path.abspath('.'))
import pdb_tools
from m_light import MEvaluator, MScope

m = MEvaluator(pdb_tools)

# Hex
assert m.eval_expr('#1') == 1, f"#1={m.eval_expr('#1')}"
assert m.eval_expr('#FF') == 255, f"#FF={m.eval_expr('#FF')}"
assert m.eval_expr('#10') == 16, f"#10={m.eval_expr('#10')}"
print('hex literals: OK')

# Numeric cast
m2 = MEvaluator(pdb_tools)
m2.eval('S X="42"')
r = m2.eval_expr('+X')
assert r == 42, f"+X={r}"
print('+X cast: OK')

# Force-compile arithmetic expressions
# Test integer division via direct eval
# The expression I\\100000 will be in SET context, not standalone eval
# For standalone, test 20\\3
m3 = MEvaluator(pdb_tools)
m3.eval('S A=10, B=3')
# Use IF condition to test arithmetic
cond = m3._eval_condition('A>0')
assert cond == True
print('IF condition: OK')

# Test that S with arithmetic works
m4 = MEvaluator(pdb_tools)
m4.eval('S RES=10+20')
print(f'S RES=10+20 → {m4.scope.get("RES")!r}')

m4.eval('S RES2=RES*2')
print(f'S RES2=RES*2 → {m4.scope.get("RES2")!r}')

# MSM style S F550=INIT\\100000#10*2
# But note: in SET context, the RHS is evaluated by _resolve
# which should trigger arithmetic evaluation
m5 = MEvaluator(pdb_tools)
m5.eval('S INIT=123456')
print('INIT set')
m5.eval('S F550= INIT ')
print(f'F550={m5.scope.get("F550")!r}')

# MSM-style arithmetic: I\100000#10*2 where I=123456
# In Python string: use double backslash
m5.eval('S I=123456')
code = r'S RES=I\100000#10*2'
m5.eval(code)
print(f'MSM I\\100000#10*2 = {m5.scope.get("RES")!r} (should be 2)')

# Test hex in condition
cond = m5._eval_condition('#10=16')
print(f'#10=16 → {cond} (should be True)')

pdb_tools._conn.close()
try: os.unlink(os.environ['PDB_PATH']); os.rmdir(tmpdir)
except: pass
print('\nDone')
