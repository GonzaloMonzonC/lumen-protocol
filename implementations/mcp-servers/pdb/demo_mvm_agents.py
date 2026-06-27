"""MVM Demo — Agentes M Autónomos"""
import sys, os, tempfile, time

tmpdir = tempfile.mkdtemp()
os.environ['PDB_PATH'] = os.path.join(tmpdir, 'demo.db')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for m in list(sys.modules.keys()):
    if 'pdb_tools' in m or 'mvm' in m:
        del sys.modules[m]
import pdb_tools
from mvm import MVM

# Poblar datos
for i in range(10):
    pdb_tools.tool_set({"ns": "DATA", "subs": [i], "value": f"sensor_{i}"})

vm = MVM(pdb_tools)

# Agente 1: Copiar ^DATA → ^MONITORED
pid1 = vm.spawn('S I="" F  S I=$O(^DATA(I)) Q:I=""  S ^M1(I)=$G(^DATA(I))', name="copy")
print(f"[1] copy (PID={pid1})")

# Agente 2: Leer ^M1 y contar
pid2 = vm.spawn('S C=0,N="" F  S N=$O(^M1(N)) Q:N=""  S C=C+1 S ^M2("count")=C', name="count")
print(f"[2] count (PID={pid2})")

# Agente 3: Alerta vacía (simula monitor)
pid3 = vm.spawn('S ^ALERTS("status")="OK"', name="alert")
print(f"[3] alert (PID={pid3})")

# Ejecutar
vm.tick()
vm.tick()
vm.tick()

# Verificar
print(f"\n{'='*50}")
print("  📋 Resultados")
print(f"{'='*50}")
r = pdb_tools.tool_get({"ns": "M1", "subs": [5]})
print(f"  ^M1(5) = {r.get('value')!r}")
assert r.get('value') == 'sensor_5', f"Expected sensor_5, got {r.get('value')}"

r = pdb_tools.tool_get({"ns": "M2", "subs": ["count"]})
print(f"  ^M2(\"count\") = {r.get('value')!r}")
assert int(float(r.get('value'))) >= 1

r = pdb_tools.tool_get({"ns": "ALERTS", "subs": ["status"]})
print(f"  ^ALERTS(\"status\") = {r.get('value')!r}")
assert r.get('value') == 'OK'

# Estado de procesos
print(f"\n{'='*50}")
print("  📊 D^SS Panel")
print(f"{'='*50}")
for p in vm.list_processes():
    print(f"  [{p['pid']}] {p['name']:10s} {p['status']:6s} PC={p['pc']}")

# Comunica entre agentes
vm.mailbox_send(pid3, {"cmd": "reread", "ts": time.time()})
msgs = vm.mailbox_read(pid3)
print(f"\n💬 mailbox({pid3}): {len(msgs)} msg(s)")
for m in msgs:
    print(f"     {m['content']}")

print(f"\n✅ MVM Demo: 3 agentes M ejecutados en PDB!")
pdb_tools._conn.close()
for f in os.listdir(tmpdir):
    try: os.unlink(os.path.join(tmpdir, f))
    except: pass
os.rmdir(tmpdir)
