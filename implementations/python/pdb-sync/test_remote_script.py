"""TEST-02: Ejecución remota de scripts vía mirroring.

1. Registrar script M en ^ROUTINE local
2. WAL entry viaja al edge
3. Edge programa ejecución vía /orq/job
4. Edge push job request al local
5. Local ejecuta DO ^script
6. Resultado vuelve al edge
"""
import sys, os, time, json

sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync"))

from pdb_tools import tool_set, tool_get, tool_order
from pdb_journal import make_entry, write, read
from pdb_ddp_client import DDPClient
from m_routines import RoutineExecutor, register

test_name = "TEST_SCRIPT_" + str(int(time.time()))
script_code = f'''
{test_name}
  S result="Hola desde M-Light!"
  W result
  Q
'''

p = 0
f = 0
def t(n, o):
    global p, f
    if o: p += 1; print(f"  ✅ {n}")
    else: f += 1; print(f"  ❌ {n}")

print("=" * 55)
print("🧪 TEST-02: Ejecución remota de scripts")
print("=" * 55)

# ── 1. Registrar script en ^ROUTINE local ──
print("\n┌─ 1. Registrar script en ^ROUTINE ────")
code = "S result=42 W result Q"
register(test_name, code)
executor = RoutineExecutor()
r = executor.exec(test_name)
t("script ejecutado localmente", r.get("result") == 42)
print(f"   Script: {test_name}")
print(f"   Resultado local: {r.get('result')}")

# ── 2. Pushear script al edge ──
print("\n┌─ 2. Pushear script al edge ──────────")
entry = make_entry("ROUTINE", test_name, json.dumps({"code": code, "type": "script"}),
                   source="local", op="set")
wr = write(entry)
t("WAL entry del script", wr.get("ok") == True)

# Push
wal = read(source="local", limit=50)
if wal:
    ddp = DDPClient()
    ddp_entries = [{
        "key": e["key"].encode().hex(),
        "value": json.dumps(e),
        "source": "local",
        "updated_at": e["ts"],
    } for e in wal]
    push_r = ddp.push("pdb", ddp_entries)
    t("script pushed to edge", "error" not in push_r)
    print(f"   Push: {push_r}")

# ── 3. Orquestador: programar ejecución ──
print("\n┌─ 3. Programar ejecución desde edge ──")
try:
    import urllib.request
    job_req = urllib.request.Request(
        "https://pdb-edge.gonzalomonzonc.workers.dev/orq/job",
        data=json.dumps({"script": test_name}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "M-Light-Test/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(job_req, timeout=15) as resp:
        job_r = json.loads(resp.read())
    t("orq job scheduled", "id" in job_r)
    print(f"   Job: {job_r.get('id', '?')} → {job_r.get('status', '?')}")
except Exception as e:
    t("orq job (puede fallar sin auth)", False)
    print(f"   ⚠️  {e}")

# ── 4. Verificar status del orquestador ──
print("\n┌─ 4. Verificar estado del orquestador ─")
try:
    import urllib.request
    req = urllib.request.Request("https://pdb-edge.gonzalomonzonc.workers.dev/orq/status", headers={"User-Agent": "M-Light-Test/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        orq_r = json.loads(resp.read())
    t("orquestador responde", "agents" in orq_r)
    print(f"   Agents: {[a['name'] for a in orq_r.get('agents', [])]}")
    print(f"   Jobs activos: {orq_r.get('jobs', {}).get('active', 0)}")
except Exception as e:
    t("orquestador reachable", False)
    print(f"   ⚠️  {e}")

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f == 0 else 1)
