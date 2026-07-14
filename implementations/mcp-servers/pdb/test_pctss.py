"""Test real %SS from PDB — with timeout via thread"""
import sys, threading, time
sys.path.insert(0, '.')
from m_light import MEvaluator
import pdb_tools

m = MEvaluator(pdb_tools)

# Build %SS script from PDB
print("=== Building %SS from PDB ===")
lines_dict = {}
key = ""
while True:
    r = pdb_tools.tool_order({"ns": "ROUTINE", "subs": ["%SS", key]})
    if r is None:
        break
    next_key = r.get("value") if isinstance(r, dict) else r
    if next_key is None or next_key == "" or next_key == key:
        break
    key = next_key
    val = pdb_tools.tool_get({"ns": "ROUTINE", "subs": ["%SS", key]})
    if isinstance(val, dict):
        v = val.get("value", "")
    else:
        v = val
    if v:
        lines_dict[float(key)] = v

print(f"Loaded {len(lines_dict)} lines from %SS")
keys = sorted(lines_dict.keys()) if lines_dict else []
if keys:
    print(f"Line range: {keys[0]} — {keys[-1]}")

# Build a flat script in order
script_lines = [lines_dict[k] for k in keys]
script = '\n'.join(script_lines)

# Execute with timeout
print()
print("=== Executing %SS (5s timeout) ===")
result = {"error": None, "done": False}

def run():
    try:
        m.eval_script(script)
        result["done"] = True
    except Exception as e:
        result["error"] = str(e)
        import traceback
        result["traceback"] = traceback.format_exc()

t = threading.Thread(target=run)
t.daemon = True
t.start()
t.join(timeout=5)

if t.is_alive():
    print("⏱️  TIMEOUT after 5s")
elif result["error"]:
    print(f"❌ %SS failed: {result['error']}")
    print(result.get("traceback", ""))
else:
    print("✅ %SS completed successfully!")
