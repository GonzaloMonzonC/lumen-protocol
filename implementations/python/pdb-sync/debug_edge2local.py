"""Edge → Local tapón."""
import sys, os, json, time
import _paths  # noqa: F401  # sys.path del stack PDB

from pdb_tools import tool_set, tool_get
from pdb_ddp_client import DDPClient
from pdb_sync_engine import SyncEngine

client = DDPClient()
engine = SyncEngine()
ts = str(int(time.time()))
key = f"edge2local_{ts}"

# 1. Edge push
entry = {
    "key": key.encode().hex(),
    "value": json.dumps({"value": "desde_edge_ok", "source": "cloud", "ns": "TEST", "key": key}),
    "source": "cloud",
    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}
r = client.push("pdb", [entry])
print("Push edge:", r)

# 2. Pull (namespace pdb)
r2 = engine.pull_and_apply("pdb")
print(f"Pull: applied={r2.get('applied')}, skipped={r2.get('skipped')}")

# 3. Verificar
r3 = tool_get({"ns": "TEST", "subs": [key]})
val = r3.get("value") if r3.get("success") else "NOT_FOUND"
print(f"Valor local: {str(val)[:80]}")

if val != "NOT_FOUND":
    print("✅ Edge → Local: DATO RECIBIDO!")
else:
    print("❌ Edge → Local: NO LLEGÓ")
    # Debug: qué hay en el pull
    if "entries" in r2:
        print(f"Entries recibidas: {len(r2.get('entries', []))}")
