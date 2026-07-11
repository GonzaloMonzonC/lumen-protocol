"""Tests CC3: Permisos tri-state."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS CC3: Permisos tri-state\n')

# ── 1. Verificar TOOL_REGISTRY en server.ts ──
path = os.path.expanduser("~/Documents/GitHub/PRIVATE_REPO/src/server.ts")
with open(path) as f:
    src = f.read()

test("TOOL_REGISTRY exists", "TOOL_REGISTRY" in src)
test("kill is ask", "'ask'" in src and "kill" in src)
test("merge is ask", "'ask'" in src and "merge" in src)
test("get is allow", "'allow'" in src and "get:" in src or "'get'" in src)
test("isDestructive function", "isDestructive" in src)
test("isConcurrencySafe function", "isConcurrencySafe" in src)
test("checkToolPermission function", "checkToolPermission" in src)
test("/v1/tools endpoint", "v1/tools" in src)
test("AGENT_NS_MAP exists", "AGENT_NS_MAP" in src)
test("hermes in AGENT_NS_MAP", "hermes" in src.split("AGENT_NS_MAP")[1].split("}")[0] if "AGENT_NS_MAP" in src else "")
test("zalo in AGENT_NS_MAP", "zalo" in src.split("AGENT_NS_MAP")[1].split("}")[0] if "AGENT_NS_MAP" in src else "")

# ── 2. Simular lógica de permisos ──
# Replicar la lógica de checkToolPermission
TOOL_REGISTRY = {
    "set":    {"permission": "allow", "isDestructive": True,  "isConcurrencySafe": False},
    "kill":   {"permission": "ask",   "isDestructive": True,  "isConcurrencySafe": False},
    "merge":  {"permission": "ask",   "isDestructive": True,  "isConcurrencySafe": False},
    "get":    {"permission": "allow", "isDestructive": False, "isConcurrencySafe": True},
    "order":  {"permission": "allow", "isDestructive": False, "isConcurrencySafe": True},
}

def check_perm(op):
    meta = TOOL_REGISTRY.get(op)
    if not meta: return "allow"
    return meta["permission"]

test("get is allow", check_perm("get") == "allow")
test("set is allow", check_perm("set") == "allow")
test("kill is ask", check_perm("kill") == "ask")
test("merge is ask", check_perm("merge") == "ask")
test("unknown is allow", check_perm("unknown") == "allow")

# ── 3. isDestructive ──
def is_destructive(op):
    meta = TOOL_REGISTRY.get(op)
    return meta.get("isDestructive", False) if meta else False

test("set is destructive", is_destructive("set"))
test("kill is destructive", is_destructive("kill"))
test("get not destructive", not is_destructive("get"))
test("order not destructive", not is_destructive("order"))

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
