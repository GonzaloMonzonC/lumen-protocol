"""Minimal IF false test"""
import os, sys, tempfile, subprocess

script = r"""
import os, sys
os.environ['PDB_PATH'] = os.path.join(os.environ['TMPDIR'], 'iftest.db')
if 'pdb_tools' in sys.modules: del sys.modules['pdb_tools']
if 'm_light' in sys.modules: del sys.modules['m_light']
sys.path.insert(0, '.')
import pdb_tools
from m_light import MEvaluator

# Test 1: IF true
m = MEvaluator(pdb_tools)
m.eval("S X=5 IF X=5 { S ^IFT(1)=42 }")
r = pdb_tools.tool_get({'ns':'IFT','subs':[1]})
print(f"IF true: value={r.get('value')}")  # Should be 42

# Test 2: IF false
m2 = MEvaluator(pdb_tools)
m2.eval("S X=3 IF X=5 { S ^IFT(2)=99 }")
r = pdb_tools.tool_get({'ns':'IFT','subs':[2]})
print(f"IF false: found={r.get('found')} value={r.get('value')}")  # Should be not found

# Debug
print(f"m2 scope X={m2.scope.get('X')}")
c = m2._eval_condition('X=5')
print(f"eval_condition X=5: {c}")
"""

env = os.environ.copy()
env['TMPDIR'] = tempfile.mkdtemp()
result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=15, env=env, cwd='.')
print(result.stdout)
if result.stderr: print("STDERR:", result.stderr[:2000])
