"""Test $GET multi-nivel — sin bash escaping."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from m_light import MEvaluator
import pdb_tools

# Test 1: regex directamente
token = '$G(^CLIMA("Tarragona","2026-07-05"))'
pat = r'\$(?:GET|G)\s*\(\^(\w+)\((.+?)\)\s*\)'
m = re.match(pat, token)
print(f"Regex match: {m is not None}")
if m:
    print(f"  ns={m.group(1)}, subs={m.group(2)}")
else:
    print("  NO MATCH — debugging...")
    # Step by step
    for step, pat_step in [
        ("\\$", r'\$'),
        ("\\$(GET|G)", r'\$(?:GET|G)'),
        ("full", pat)
    ]:
        m2 = re.match(pat_step, token)
        print(f"  {step:15s} → {'MATCH' if m2 else 'NO MATCH'}")

# Test 2: eval_expr
m = MEvaluator(pdb_tools)
val = m.eval_expr('$G(^CLIMA("Tarragona","2026-07-05"))')
print(f"\neval_expr: {val}")
