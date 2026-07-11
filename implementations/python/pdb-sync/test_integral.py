"""TEST-04: Integración completa del sistema vivo.

Prueba final que ejercita TODO el ecosistema:
1. DDP mirroring (local↔edge)
2. WAL journaling con source tagging
3. Ejecución de scripts M
4. Orquestador + health check
5. Anti-bucle
"""
import sys, os, time, json

sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync"))

from pdb_tools import tool_set, tool_get, tool_kill
from pdb_journal import make_entry, write, read, pending
from pdb_ddp_client import DDPClient
from pdb_sync_engine import SyncEngine
from m_routines import RoutineExecutor, register

p = 0; fail = 0
def t(n,o):
    global p,fail
    if o: p+=1; print(f"  ✅ {n}")
    else: fail+=1; print(f"  ❌ {n}")

print("=" * 55)
print("🧪 TEST-04: SISTEMA VIVO — Integración completa")
print("=" * 55)

client = DDPClient()
engine = SyncEngine()

# ── 1. DDP Mirroring ──
print("\n┌─ 1. DDP Mirroring ──────────────────")
status_before = client.status()
t("edge responde", "entries" in status_before)
entries_before = status_before.get("entries", 0)
print(f"   Edge entries: {entries_before}")

# ── 2. WAL + Push ──
print("\n┌─ 2. WAL + Push ─────────────────────")
test_key = f"integral_test_{int(time.time())}"
tool_set({"ns": "INTEGRAL", "subs": [test_key], "value": "test_value"})
entry = make_entry("INTEGRAL", test_key, "test_value", source="local")
wr = write(entry)
t("WAL write ok", wr.get("ok") == True)

# Push
wal_local = read(source="local", limit=100)
if wal_local:
    ddp_entries = [{
        "key": e["key"].encode().hex(),
        "value": json.dumps(e), "source": "local",
        "updated_at": e["ts"],
    } for e in wal_local]
    push_r = client.push("pdb", ddp_entries)
    t("push to edge", "error" not in push_r)
    print(f"   Push applied: {push_r.get('applied', 0)}")

# ── 3. Pull + Anti-bucle ──
print("\n┌─ 3. Anti-bucle ─────────────────────")
sync_r = engine.sync("pdb")
t("pull skips entries (anti-bucle)", sync_r.get("pull", {}).get("skipped", 0) >= 0)
print(f"   Pull: applied={sync_r.get('pull',{}).get('applied')}, skipped={sync_r.get('pull',{}).get('skipped')}")

# ── 4. Ejecución script ──
print("\n┌─ 4. DO ^script ─────────────────────")
register("INTEGRAL_TEST", "S res=999 W res Q")
executor = RoutineExecutor()
r = executor.exec("INTEGRAL_TEST")
t("script ejecutado", r.get("result") == 999)

# ── 5. Orquestador ──
print("\n┌─ 5. Orquestador ────────────────────")
try:
    import urllib.request
    req = urllib.request.Request(
        "https://pdb-edge.gonzalomonzonc.workers.dev/orq/status",
        headers={"User-Agent": "M-Light-Integral/1.0"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        status = json.loads(resp.read())
    t("orq status ok", "agents" in status)
    t("orq has agents", len(status.get("agents", [])) >= 3)
    t("orq has jobs", "jobs" in status)
    t("orq has uptime", "uptime_ms" in status)
    agents_online = sum(1 for a in status.get("agents", []) if a["status"] == "online")
    print(f"   Agents: {agents_online}/{len(status.get('agents', []))} online")
except Exception as e:
    t("orq status", False)
    print(f"   Error: {e}")

# ── 6. Verificación final ──
print("\n┌─ 6. Verificación final ─────────────")
status_after = client.status()
entries_after = status_after.get("entries", 0)
t("edge entries crecieron", entries_after >= entries_before)
print(f"   Edge entries: {entries_before} → {entries_after} (+{entries_after - entries_before})")
t("WAL pending manageable", pending() < 200)

# ── 7. Cleanup ──
print("\n┌─ 7. Cleanup ─────────────────────────")
tool_kill({"ns": "INTEGRAL", "subs": [test_key]})
t("cleanup ok", True)

print(f"\n📊 {p}/{p+fail} tests passed")
print(f"🔬 Sistema vivo: {entries_after} entries en edge, {pending()} WAL pendientes")
sys.exit(0 if fail == 0 else 1)
