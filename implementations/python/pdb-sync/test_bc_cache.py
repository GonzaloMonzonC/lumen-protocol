"""Test bytecode cache from RoutineExecutor."""
import sys, os
import _paths  # noqa: F401  # sys.path del stack PDB

from m_routines import RoutineExecutor, register

# First exec (compile + cache)
register("BC1", "S x=42")
executor = RoutineExecutor()

r1 = executor.exec("BC1")
print(f"1st exec: result={r1.get('result')}, error={r1.get('error', 'none')}")

# Second exec (from cache)
r2 = executor.exec("BC1")
print(f"2nd exec: result={r2.get('result')}, error={r2.get('error', 'none')}")

# Third exec with different data
register("BC2", "S y=99")
r3 = executor.exec("BC2")
print(f"3rd exec (different): result={r3.get('result')}")

print("\n✅ Cache test complete")
