"""Test mirroring bidireccional: edge↔local y local↔edge."""
import sys, os, json, time

sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync"))

from pdb_tools import tool_set, tool_get, tool_kill
from pdb_journal import make_entry, write, read
from pdb_ddp_client import DDPClient
from pdb_sync_engine import SyncEngine

p = 0; fail = 0
def t(n,o):
    global p,fail
    if o: p+=1; print(f"  ✅ {n}")
    else: fail+=1; print(f"  ❌ {n}")

client = DDPClient()
engine = SyncEngine()
ts = str(int(time.time()))

print("=" * 55)
print("🧪 Mirroring BIDIRECCIONAL")
print("=" * 55)

# ── DIRECCIÓN 1: Local → Edge ──
print("\n┌─ ➡️  LOCAL → EDGE ──────────────────")
key1 = f"mirror_local_{ts}"
tool_set({"ns": "TEST", "subs": [key1], "value": "desde_local"})
entry = make_entry("TEST", key1, "desde_local", source="local")
write(entry)
t("1a. local write ok", tool_get({"ns":"TEST","subs":[key1]}).get("value") == "desde_local")

# Push
wal = read(source="local", limit=100)
batch = [{"key": e["key"].encode().hex(), "value": json.dumps(e), "source": "local", "updated_at": e["ts"]} for e in wal]
r = client.push("pdb", batch)
t("1b. push to edge", r.get("applied",0) > 0)
print(f"   Push: {r.get('applied',0)} applied")

# ── DIRECCIÓN 2: Edge → Local (simular que un agente escribe en edge) ──
print("\n┌─ ⬅️  EDGE → LOCAL ──────────────────")
key2 = f"mirror_edge_{ts}"
# Escribir directamente en edge via DDP push con source=cloud
edge_entry = {
    "key": key2.encode().hex(),
    "value": json.dumps({"value": "desde_edge", "source": "cloud", "ns": "TEST", "key": key2}),
    "source": "cloud",
    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}
r2 = client.push("pdb", [edge_entry])
t("2a. edge write ok", "error" not in r2)
print(f"   Edge push: {r2}")

# Pull para traerlo a local (anti-bucle debe saltar source=local, aplicar source=cloud)
r3 = engine.pull_and_apply("pdb")
t("2b. pull from edge", "applied" in r3)
print(f"   Pull: applied={r3.get('applied')}, skipped={r3.get('skipped')}")

# Verificar en local
r4 = tool_get({"ns": "TEST", "subs": [key2]})
val = r4.get("value", "") if r4.get("success") else "NOT_FOUND"
try: val = json.loads(val).get("value", val) if val.startswith("{") else val
except: pass
t("2c. edge data reached local", "edge" in str(val) or val != "NOT_FOUND")
print(f"   Valor en local: {str(val)[:50]}")

# ── VERIFICACIÓN FINAL ──
print("\n┌─ 📊 VERIFICACIÓN ────────────────────")
status = client.status()
t("edge entries ok", status.get("entries", 0) > 0)
print(f"   Edge entries: {status.get('entries')}")
t("WAL pending manageable", len(read(source="local", limit=200)) < 200)

# Cleanup
tool_kill({"ns": "TEST", "subs": [key1]})
tool_kill({"ns": "TEST", "subs": [key2]})
print(f"   Cleanup done")

print(f"\n📊 {p}/{p+fail} tests passed")
sys.exit(0 if fail == 0 else 1)
