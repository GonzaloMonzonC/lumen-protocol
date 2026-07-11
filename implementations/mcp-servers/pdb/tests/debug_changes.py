"""Debug: test tool_get con claves float de CHANGES."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdb_tools import tool_order, tool_get, tool_query, _decode_value
import json

# Obtener via SQL + _decode_value para evitar precisión float
r = tool_query({"sql": "SELECT subkey, value FROM _globals WHERE ns=? AND length(value) > 10 ORDER BY rowid ASC LIMIT 5", "params": ["CHANGES"]})
if r.get("success"):
    for i, row in enumerate(r.get("rows", [])):
        raw_val = row.get("value")
        val = _decode_value(raw_val)
        print(f"  #{i}: type={type(val).__name__}", end="")
        if isinstance(val, dict):
            print(f" op={val.get('op','?')} ns={val.get('ns','?')} subs={str(val.get('subs',[]))[:30]}")
        elif isinstance(val, str):
            print(f" str={val[:60]}")
        else:
            print(f" val={str(val)[:60]}")
else:
    print(f"Error: {r}")
