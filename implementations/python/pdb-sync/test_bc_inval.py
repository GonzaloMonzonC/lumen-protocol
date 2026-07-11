"""Test BC cache invalidation on source change."""
import sys, os
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync"))

from m_routines import RoutineExecutor, register
from pdb_tools import tool_get, tool_set

executor = RoutineExecutor()

# Register v1
register("INVAL", "S x=1")
r1 = executor.exec("INVAL")
print(f"v1: x={r1.get('vars',{}).get('x')}")

# Check cache exists
bc_cs = tool_get({"ns":"ROUTINE","subs":["INVAL","BC_INVAL","_cs"]})
print(f"Cache CS: {bc_cs.get('value')}")

# Register v2 (same name, different code)
register("INVAL", "S x=99")
r2 = executor.exec("INVAL")
print(f"v2 (changed source): x={r2.get('vars',{}).get('x')}")

if r2.get('vars',{}).get('x') == 99:
    print("✅ Cache invalidated and recompiled!")
else:
    print("❌ Cache not invalidated")
