"""Approach: use SQL + _decode_value for CHANGES recovery."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdb_tools import _decode_value
from pdb_tools import tool_set, tool_get, tool_kill

# Direct SQL approach
import sqlite3
db = sqlite3.connect('file:C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb/lumen-pdb.db?mode=ro', uri=True)

rows = db.execute("SELECT subkey, value FROM _globals WHERE ns=? AND LENGTH(value) > 10 AND subkey NOT LIKE '%file%' AND subkey NOT LIKE '%control%' LIMIT 3", 
                  ('CHANGES',)).fetchall()

print(f"Found {len(rows)} rows")
for subkey, raw_val in rows:
    val = _decode_value(raw_val)
    print(f"type={type(val).__name__}", end="")
    if isinstance(val, dict):
        print(f" op={val.get('op','?')} ns={val.get('ns','?')} ts={str(val.get('timestamp',''))[:19]}")
    elif isinstance(val, str):
        try:
            import json
            v2 = json.loads(val)
            print(f" -> dict op={v2.get('op','?')} ns={v2.get('ns','?')}")
        except:
            print(f" raw={val[:60]}")
    else:
        print(f" value={str(val)[:60]}")
