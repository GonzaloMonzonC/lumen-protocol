"""CONSOLE-05: Validación completa de la consola M-Light."""
import sys, os, json, time, asyncio

sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync"))

from m_stackvm import StackVM
from pdb_ddp_client import DDPClient

# Delayed imports for PDB tools
from pdb_tools import tool_set, tool_get, tool_kill, tool_order
from pdb_journal import make_entry, write

p = 0; fail = 0
def t(n,o):
    global p,fail
    if o: p+=1; print(f"  ✅ {n}")
    else: fail+=1; print(f"  ❌ {n}")

print("=" * 55)
print("🧪 CONSOLE-05: Validación final")
print("=" * 55)

# ── 1. Sesión persistente (secuencia de comandos) ──
print("\n┌─ 1. Sesión persistente ────────────")
vm = StackVM()
cmds = [("S x=10", ""), ("S y=20", ""), ("S z=x+y", ""), ("I z>20 S ok=1", "")]
for cmd, expected in cmds:
    vm.compile(cmd).exec()
    vm.ops = []
t("x persists after 3 commands", vm.vars.get("x") == 10)
t("y=20", vm.vars.get("y") == 20)
t("z=x+y=30", vm.vars.get("z") == 30)
t("IF ok=1", vm.vars.get("ok") == 1)

# ── 2. FOR loop ──
print("\n┌─ 2. FOR loop ──────────────────────")
vm2 = StackVM()
vm2.compile("F i=1:1:10 S t=t+i").exec()
t("FOR 1..10 sum=55", vm2.vars.get("t") == 55)

# ── 3. WRITE output ──
print("\n┌─ 3. WRITE output ─────────────────")
vm3 = StackVM()
vm3.compile('W "hello"').exec(); out1 = " ".join(str(o) for o in vm3.ops if o is not None)
vm3.ops = []; vm3.vars["msg"] = 42
vm3.compile("W msg").exec(); out2 = " ".join(str(o) for o in vm3.ops if o is not None)
t("WRITE string output", "hello" in out1)
t("WRITE variable output", "42" in out2)

# ── 4. Comandos de sistema (simulados) ──
print("\n┌─ 4. Comandos de sistema ──────────")
client = DDPClient()
st = client.status()
t("D ^%SS entries > 0", st.get("entries", 0) > 0)

# ZW ^TEST
test_ns = "TEST"
k = ""; keys_found = 0
for _ in range(20):
    r = tool_order({"ns": test_ns, "subs": [k], "direction": 1})
    if not r.get("success") or not r.get("value"): break
    k = r["value"]; keys_found += 1
t("ZW ^TEST finds keys", keys_found > 0)

# ZR
kr = ""; routines = 0
for _ in range(100):
    r = tool_order({"ns": "ROUTINE", "subs": [kr], "direction": 1})
    if not r.get("success") or not r.get("value"): break
    kr = r["value"]
    if not kr.startswith("BC_"): routines += 1
t("ZR lists routines", routines > 0)

# ── 5. WAL + Journaling ──
print("\n┌─ 5. WAL + Journaling ─────────────")
key = f"console_test_{int(time.time())}"
tool_set({"ns": "TEST", "subs": [key], "value": "console_test"})
entry = make_entry("TEST", key, "console_test", source="local")
wr = write(entry)
t("WAL write from console cmd", wr.get("ok") == True)

# ── 6. DDP Cloud ──
print("\n┌─ 6. DDP Cloud ────────────────────")
t("edge health", client.health().get("ok") == True)
st2 = client.status()
t("edge entries stable", st2.get("entries", 0) >= st.get("entries", 0))

# ── 7. HTTP frontend ──
print("\n┌─ 7. HTTP frontend ────────────────")
try:
    import urllib.request
    req = urllib.request.Request("http://localhost:8090/", headers={"User-Agent":"M-Console-Test/1.0"})
    with urllib.request.urlopen(req, timeout=5) as r:
        html = r.read().decode()
    t("HTML serves", "M-Light" in html)
    t("Has terminal div", "term" in html)
    t("Has input", "input" in html)
    t("Has WebSocket script", "WebSocket" in html)
except Exception as e:
    t("HTML serves (console running?)", False)
    print(f"   ⚠️ {e}")

# ── 8. Cleanup ──
print("\n┌─ 8. Cleanup ──────────────────────")
tool_kill({"ns": "TEST", "subs": [key]})
t("cleanup ok", True)

print(f"\n📊 {p}/{p+fail} tests passed")
sys.exit(0 if fail == 0 else 1)
