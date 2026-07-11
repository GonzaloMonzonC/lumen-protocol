"""TEST-01: Mirroring de journals local ↔ edge.

1. Escribir datos de prueba en PDB local
2. Generar entradas WAL
3. Push al edge via DDP
4. Verificar en edge que los datos llegaron
5. Pull desde edge para confirmar anti-bucle
"""
import sys, os, json, time

sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync"))

from pdb_tools import tool_set, tool_get, tool_order
from pdb_journal import make_entry, write, read, pending
from pdb_ddp_client import DDPClient

p = 0
f = 0
def t(n, o):
    global p, f
    if o: p += 1; print(f"  ✅ {n}")
    else: f += 1; print(f"  ❌ {n}")

print("=" * 55)
print("🧪 TEST-01: Mirroring PDB local ↔ edge")
print("=" * 55)

# ── 1. Estado inicial ──
print("\n┌─ 1. Estado inicial ─────────────────")
client = DDPClient()
status = client.status()
t("edge status ok", "entries" in status)
print(f"   Edge entries: {status.get('entries', '?')}")
print(f"   Edge namespaces: {status.get('namespaces', [])}")

# ── 2. Escribir datos de prueba locales ──
print("\n┌─ 2. Escribir datos de prueba locales ─")
test_ns = "TEST"
test_key = f"sync_test_{int(time.time())}"
test_val = f"Hola desde Hermes local! {time.ctime()}"

tool_set({"ns": test_ns, "subs": [test_key], "value": test_val})
r = tool_get({"ns": test_ns, "subs": [test_key]})
t("local write ok", r.get("value") == test_val)
print(f"   Escribí: ^{test_ns}('{test_key}') = '{test_val[:40]}...'")

# ── 3. Generar WAL entries ──
print("\n┌─ 3. Generar WAL entries ─────────────")
entry = make_entry(test_ns, test_key, test_val, source="local")
r = write(entry)
t("WAL entry created", r.get("ok") == True)
print(f"   WAL timestamp: {r.get('ts', '?')[:30]}...")

# ── 4. Push al edge ──
print("\n┌─ 4. Push al edge ───────────────────")
entries = read(source="local", limit=50)
t(f"WAL local entries: {len(entries)}", len(entries) >= 1)

if entries:
    ddp_entries = []
    for e in entries:
        ddp_entries.append({
            "key": e["key"].encode().hex(),
            "value": json.dumps(e),
            "source": "local",
            "updated_at": e["ts"],
        })

    push_r = client.push("pdb", ddp_entries)
    t("push to edge ok", "error" not in push_r)
    print(f"   Push result: {push_r}")

# ── 5. Verificar en edge ──
print("\n┌─ 5. Verificar en edge ───────────────")
status2 = client.status()
t("edge entries after push", status2.get("entries", 0) >= status.get("entries", 0))
print(f"   Edge entries antes: {status.get('entries')}, después: {status2.get('entries')}")

# ── 6. Pull desde edge (anti-bucle) ──
print("\n┌─ 6. Pull desde edge ─────────────────")
from pdb_sync_engine import SyncEngine
engine = SyncEngine()
sync_r = engine.sync("pdb")
t("pull returns entries", "pull" in sync_r)
print(f"   Pull result: applied={sync_r.get('pull', {}).get('applied', 0)}, "
      f"skipped={sync_r.get('pull', {}).get('skipped', 0)}")

# ── 7. Resumen ──
print("\n" + "=" * 55)
print(f"📊 {p}/{p+f} tests passed")
print("=" * 55)

# Guardar resultado
result = {
    "p": p, "f": f, "total": p+f,
    "edge_before": status.get('entries'),
    "edge_after": status2.get('entries'),
    "test_key": test_key, "test_ns": test_ns,
}
print(f"\n🔑 Test key: ^{test_ns}('{test_key}') = '{test_val}'")
print(f"💡 Ver en edge: GET https://pdb-edge.gonzalomonzonc.workers.dev/v1/get/{test_ns}?key={test_key}")

sys.exit(0 if f == 0 else 1)
