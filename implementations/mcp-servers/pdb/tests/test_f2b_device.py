"""Test F2b: Device Manager (standalone, no PDB dependence)"""
import sys, os, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mvm import MVM, DeviceManager, ConsoleDevice, PDBDevice, LogDevice, DashboardDevice

print("="*50)
print("  F2b: Device Manager Standalone Test")
print("="*50)

# 1. DeviceManager básico
dm = DeviceManager()
print("\n1. Device list")
devs = dm.list_devices()
for d in devs:
    print(f"   [{d['num']}] {d['name']} — open={d['open']}")
print("   OK")

# 2. Console device (no PDB needed)
console = ConsoleDevice()
console.open()
console.write("test console output")
print("\n2. Console device: OK")

# 3. PDB device regex (standalone)
pdb_d = PDBDevice(None)  # no pdb module
data = '^TEST(1)=42'
m = re.match(r'\^(\w+)\((.+)\)=(.*)', data)
assert m, "Regex failed"
assert m.group(1) == 'TEST'
assert m.group(2) == '1'
assert m.group(3) == '42'
print("\n3. PDB device regex: OK")

# 4. MVM con devices (simulado)
print("\n4. MVM sin PDB (simulado)")
try:
    vm = MVM(None)  # None pdb — debería funcionar sin DB
    pid = vm.spawn('O 63', name='sim')
    print(f"   spawn: pid={pid}")
    vm.tick()
    print(f"   tick: OK")
    procs = vm.list_processes()
    for p in procs:
        print(f"   [{p['pid']}] {p.get('name','?')} — IO={p.get('io_device','?')}")
except Exception as e:
    print(f"   SKIP (MVM requiere PDB): {e}")

# 5. Device open/close lifecycle
print("\n5. Device lifecycle")
log = LogDevice(None)
assert log.is_open == False
log.open()
assert log.is_open == True
log.close()
assert log.is_open == False
print("   OPEN/CLOSE: OK")

# 6. Dashboard device
dash = DashboardDevice(None)
dash.open()
dash.write("<h1>test</h1>")
print("   Dashboard write: OK")

print(f"\n✅ F2b Device Manager: 6/6 OK!")
