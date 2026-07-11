#!/usr/bin/env python3
"""Test $GET multi-nivel fix en M-Light."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from m_light import MEvaluator
import pdb_tools

m = MEvaluator(pdb_tools)

# Test $GET multi-nivel
tests = [
    ('$G(^CLIMA("Tarragona","2026-07-05"))', 26),
    ('$G(^CLIMA("Madrid","2026-07-06"))', 37),
    ('$G(^CLIMA("Pamplona","2026-07-08"))', 19),
    ('$D(^CLIMA("Tarragona","2026-07-05"))', 1),
    ('$D(^CLIMA("NoExiste","2026-01-01"))', 0),
]

passed = failed = 0
for expr, expected in tests:
    val = m.eval_expr(expr)
    ok = val == expected
    if ok: passed += 1
    else: failed += 1
    status = "✅" if ok else f"❌ (got {val}, expected {expected})"
    print(f"  {status}  {expr}")

print(f"\n📊 {passed}/{passed+failed} tests passed")
