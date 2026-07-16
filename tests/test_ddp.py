import subprocess, json, sys

BASE = "http://localhost:8081"

def ddp_push(ns, entries):
    r = subprocess.run(["curl", "-s", "--max-time", "5", "-X", "POST", f"{BASE}/ddp/push",
        "-H", "Content-Type: application/json",
        "-d", json.dumps({"ns": ns, "entries": entries})], capture_output=True)
    return json.loads(r.stdout)

def ddp_pull(ns):
    r = subprocess.run(["curl", "-s", "--max-time", "5", f"{BASE}/ddp/pull?ns={ns}"], capture_output=True)
    return json.loads(r.stdout)

def health():
    r = subprocess.run(["curl", "-s", "--max-time", "5", f"{BASE}/health"], capture_output=True)
    return json.loads(r.stdout)

passed = 0
failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print("=== DDP Tests ===\n")

h = health()
test("Health", h.get("ok") == True)

r = ddp_push("T_A", [{"subs": ["msg"], "value": "hola"}])
test("Push", r.get("success") == True)
d = ddp_pull("T_A")
test("Pull", d.get("entries")[0]["value"] == "hola")

r = ddp_push("T_A", [{"subs": ["msg"], "value": "modif"}])
d = ddp_pull("T_A")
test("Update", d["entries"][0]["value"] == "modif")

r = ddp_push("T_B", [{"subs": ["x"], "value": 42}])
d = ddp_pull("T_B")
test("Numeric", d["entries"][0]["value"] == 42)

r = ddp_push("T_C", [{"subs": [], "value": "raiz"}])
d = ddp_pull("T_C")
test("Root (subs=[])", d["entries"][0]["value"] == "raiz")

r = ddp_push("T_D", [{"subs": ["a"], "value": 1}, {"subs": ["b"], "value": 2}])
d = ddp_pull("T_D")
test("Multi entries", len(d["entries"]) == 2)

d = ddp_pull("DOESNOTEXIST")
test("Non-existent ns", len(d.get("entries",[])) == 0)

print(f"\n=== {passed}/{passed+failed} ===\n")
sys.exit(0 if failed == 0 else 1)
