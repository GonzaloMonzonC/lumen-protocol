"""Tests CONSOLE: M-Light terminal web + comandos."""
import sys, os, json, time, asyncio

sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync"))

from m_stackvm import StackVM
from pdb_ddp_client import DDPClient

p = 0; fail = 0
def t(n,o):
    global p,fail
    if o: p+=1; print(f"  ✅ {n}")
    else: fail+=1; print(f"  ❌ {n}")

print("=" * 55)
print("🧪 CONSOLE TESTS")
print("=" * 55)

# ── 1. Sesión persistente ──
print("\n┌─ 1. Sesión VM persistente ────────")
vm = StackVM()
vm.compile("S x=42").exec(); vm.ops = []
vm.compile("S y=x+8").exec()
t("x persists between commands", vm.vars.get("x") == 42)
t("y calculated from x", vm.vars.get("y") == 50)

# ── 2. Comandos M básicos ──
print("\n┌─ 2. Comandos M básicos ───────────")
vm2 = StackVM()
vm2.compile("S a=10").exec(); vm2.ops = []
vm2.compile("S b=20").exec(); vm2.ops = []
vm2.compile("S c=a+b").exec()
t("SET + aritmética", vm2.vars.get("c") == 30)
vm2.compile("I c>20 S ok=1").exec()
t("IF condicional", vm2.vars.get("ok") == 1)
vm2.compile("F i=1:1:5 S t=t+i").exec()
t("FOR loop 1..5", vm2.vars.get("t", 0) == 15)

# ── 3. WRITE output ──
print("\n┌─ 3. WRITE output ─────────────────")
vm3 = StackVM()
vm3.compile('W "hola"').exec()
t("WRITE string", len(vm3.ops) > 0)
vm3.ops = []
vm3.compile("S msg=42 W msg").exec()
t("WRITE variable", "42" in str(vm3.ops))

# ── 4. Comandos de sistema ──
print("\n┌─ 4. Sistema (%SS, ZW, ZR) ────────")
# %SS via DDP
client = DDPClient()
st = client.status()
t("D ^%SS returns entries", st.get("entries", 0) > 0)
t("D ^%SS has lag_ms", "lag_ms" in st)

# ZW via PDB tools
from pdb_tools import tool_order, tool_get
test_ns = "TEST"
k = ""; found = False
for _ in range(20):
    r = tool_order({"ns": test_ns, "subs": [k], "direction": 1})
    if not r.get("success") or not r.get("value"): break
    k = r["value"]; found = True
    break
t("ZW ^NS finds keys", found)

# ZR via PDB tools
kr = ""; has_routines = False
for _ in range(50):
    r = tool_order({"ns": "ROUTINE", "subs": [kr], "direction": 1})
    if not r.get("success") or not r.get("value"): break
    kr = r["value"]; has_routines = True
    break
t("ZR lists routines", has_routines)

# ── 5. DDP Cloud ──
print("\n┌─ 5. DDP Cloud ────────────────────")
t("edge health", client.health().get("ok") == True)
t("edge has entries", client.status().get("entries", 0) > 0)

# ── 6. HTML sirve ──
print("\n┌─ 6. HTTP frontend ────────────────")
try:
    import urllib.request
    req = urllib.request.Request("http://localhost:8085/", headers={"User-Agent":"M-Console-Test/1.0"})
    with urllib.request.urlopen(req, timeout=5) as r:
        html = r.read().decode()
    t("HTML page serves", "M-Light" in html)
    t("Has terminal div", "term" in html)
    t("Has input field", "input" in html)
except Exception as e:
    t("HTML page serves (console must be running)", False)

print(f"\n📊 {p}/{p+fail} tests passed")
sys.exit(0 if fail == 0 else 1)
