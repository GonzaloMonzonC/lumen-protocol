"""Test OBJ-4: GOTO, DO, labels"""
import sys, os
sys.path.insert(0, os.path.abspath('.'))
from m_light import MEvaluator

# Test GOTO
script = """
S X=1
G SKIP
S X=999
SKIP S X=42
"""
m = MEvaluator()
m.eval_script(script)
assert m.scope.get('X') == 42
print(f'GOTO: X=42 ✅')

# Test GOTO CONT (MSM style)
script2 = """
S RES=""
G CONT
S RES="SKIPPED"
CONT S RES="OK"
"""
m2 = MEvaluator()
m2.eval_script(script2)
assert m2.scope.get('RES') == 'OK'
print(f'GOTO CONT: RES=OK ✅')

# Test DO with QUIT returning
script3 = """
D SUB
S RES="AFTER"
Q
SUB S RES="SUBROUTINE"
Q
"""
m3 = MEvaluator()
m3.eval_script(script3)
assert m3.scope.get('RES') == 'AFTER', f"DO: RES={m3.scope.get('RES')!r}"
print(f'DO + Q return: RES=AFTER ✅')

# Test nested DO
script4 = """
S ^LOG("start")=1
D SUB1
S ^LOG("end")=1
Q
SUB1 S ^LOG("sub1")=1
D SUB2
Q
SUB2 S ^LOG("sub2")=1
Q
"""
import os, tempfile
tmpdir = tempfile.mkdtemp()
os.environ['PDB_PATH'] = os.path.join(tmpdir, 't.db')
import pdb_tools
m4 = MEvaluator(pdb_tools)
m4.eval_script(script4)
assert pdb_tools.tool_get({'ns':'LOG','subs':['start']})['value'] == 1
assert pdb_tools.tool_get({'ns':'LOG','subs':['sub1']})['value'] == 1
assert pdb_tools.tool_get({'ns':'LOG','subs':['sub2']})['value'] == 1
assert pdb_tools.tool_get({'ns':'LOG','subs':['end']})['value'] == 1
print(f'Nested DO: all OK ✅')

pdb_tools._conn.close()
try: os.unlink(os.environ['PDB_PATH']); os.rmdir(tmpdir)
except: pass

print('\n✅ OBJ-4: GOTO + DO completos!')
