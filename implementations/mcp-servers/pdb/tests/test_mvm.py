"""Test MVM — M Virtual Machine"""
import sys, os, tempfile, time

tmpdir = tempfile.mkdtemp()
os.environ['PDB_PATH'] = os.path.join(tmpdir, 'vm_test.db')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Force fresh PDB
for m in list(sys.modules.keys()):
    if 'pdb_tools' in m:
        del sys.modules[m]

import pdb_tools
from mvm import MVM

print("=" * 55)
print("  🖥️  MVM — M Virtual Machine Test")
print("=" * 55)

# Crear VM
vm = MVM(pdb_tools)

# Test 1: Spawnear un proceso simple
print("\n📌 Test 1: Spawn proceso simple")
pid1 = vm.spawn('S ^DATA("t1")="hello"', name="test1")
print(f"   PID={pid1} creado")
vm.tick()
r = pdb_tools.tool_get({"ns": "DATA", "subs": ["t1"]})
print(f"   ^DATA(\"t1\") = {r.get('value')!r}")
assert r.get('value') == 'hello', f"Expected hello, got {r.get('value')}"

# Test 2: Spawnear un proceso que itera
print("\n📌 Test 2: Proceso con \$ORDER")
# Poblar datos
pdb_tools.tool_set({"ns": "T2", "subs": ["a"], "value": "1"})
pdb_tools.tool_set({"ns": "T2", "subs": ["b"], "value": "1"})
pdb_tools.tool_set({"ns": "T2", "subs": ["c"], "value": "1"})

pid2 = vm.spawn(
    'S N="" F  S N=$O(^T2(N)) Q:N=""  S ^RES(N)=N',
    name="iterator"
)
print(f"   PID={pid2} creado")
vm.tick(max_per_process=50)
for k in ['a', 'b', 'c']:
    r = pdb_tools.tool_get({"ns": "RES", "subs": [k]})
    assert r.get('value') == k, f"^RES({k}) = {r.get('value')!r}"
print(f"   ^RES(a,b,c) = OK")

# Test 3: Listar procesos
print("\n📌 Test 3: Lista de procesos")
procs = vm.list_processes()
for p in procs:
    print(f"   [{p['pid']}] {p['name']}: {p['status']} (PC={p['pc']}, vars={p['vars']})")
assert len(procs) >= 2, f"Expected >=2 processes, got {len(procs)}"

# Test 4: Mailbox
print("\n📌 Test 4: Cola de mensajes")
vm.mailbox_send(pid1, "hello from test!")
vm.mailbox_send(pid1, {"command": "restart", "timestamp": time.time()})
msgs = vm.mailbox_read(pid1)
print(f"   Mensajes recibidos: {len(msgs)}")
for msg in msgs:
    print(f"     [{msg['id']}] {msg['content']}")
assert len(msgs) == 2, f"Expected 2 messages, got {len(msgs)}"

# Test 5: Kill process
print("\n📌 Test 5: Kill proceso")
vm.kill(pid1)
p1 = vm.get_process(pid1)
assert p1.status == 'DEAD', f"Expected DEAD, got {p1.status}"
print(f"   PID={pid1}: {p1.status}")

# Test 6: Proceso con múltiples slices
print("\n📌 Test 6: Proceso largo (múltiples slices)")
pdb_tools.tool_set({"ns": "T6", "subs": [1], "value": "A"})
pdb_tools.tool_set({"ns": "T6", "subs": [2], "value": "B"})
pdb_tools.tool_set({"ns": "T6", "subs": [3], "value": "C"})

pid3 = vm.spawn(
    'S I="" F  S I=$O(^T6(I)) Q:I=""  S ^R6(I)=I',
    name="long_iter"
)
# Ejecutar en varios ticks pequeños
for _ in range(5):
    vm.tick(max_per_process=20)
    time.sleep(0.1)
p3 = vm.get_process(pid3)
print(f"   [{pid3}] status={p3.status} PC={p3.pc}")
for i in [1, 2, 3]:
    r = pdb_tools.tool_get({"ns": "R6", "subs": [i]})
    print(f"     ^R6({i}) = {r.get('value')!r}")

# Cleanup
pdb_tools._conn.close()
for f in os.listdir(tmpdir):
    try: os.unlink(os.path.join(tmpdir, f))
    except: pass
os.rmdir(tmpdir)

print(f"\n{'='*55}")
print("  ✅ MVM Tests completados!")
print(f"{'='*55}")
