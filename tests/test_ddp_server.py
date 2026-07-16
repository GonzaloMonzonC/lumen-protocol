import subprocess, json, sys

BASE = "http://192.168.1.11:8081"

def ddp_push(ns, entries):
    r = subprocess.run(["curl", "-s", "--max-time", "5", "-X", "POST", f"{BASE}/ddp/push",
        "-H", "Content-Type: application/json",
        "-d", json.dumps({"ns": ns, "entries": entries})], capture_output=True)
    return json.loads(r.stdout)

def ddp_pull(ns):
    r = subprocess.run(["curl", "-s", "--max-time", "5", f"{BASE}/ddp/pull?ns={ns}"], capture_output=True)
    return json.loads(r.stdout)

passed = 0
failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print("=== DDP Tests ===\n")

h = subprocess.run(["curl", "-s", f"{BASE}/health"], capture_output=True)
test("Health endpoint", b"ok" in h.stdout)

r = ddp_push("TEST_SUITE", [{"subs": ["msg"], "value": "hola_test"}])
test("Push simple", r.get("success"))
d = ddp_pull("TEST_SUITE")
test("Pull simple", d["entries"][0]["value"] == "hola_test")

r = ddp_push("TEST_ROOT", [{"subs": [], "value": "raiz"}])
test("Push root (subs=[])", r.get("success"))
d = ddp_pull("TEST_ROOT")
test("Pull root", d["entries"][0]["value"] == "raiz")

r = ddp_push("TEST_MULTI", [{"subs": ["a"], "value": 1}, {"subs": ["b"], "value": 2}])
test("Push multi", r.get("success") and r.get("count") == 2)
d = ddp_pull("TEST_MULTI")
test("Pull multi", len(d["entries"]) == 2)

r = ddp_push("TEST_SUITE", [{"subs": ["msg"], "value": "modif"}])
d = ddp_pull("TEST_SUITE")
test("Update entry", d["entries"][0]["value"] == "modif")

d = ddp_pull("_all_")
ns = [e["ns"] for e in d.get("entries",[])]
test("_all_ has TEST_SUITE", "TEST_SUITE" in ns)
test("_all_ has TEST_ROOT", "TEST_ROOT" in ns)

d = ddp_pull("DOES_NOT_EXIST")
test("Empty ns", len(d.get("entries",[])) == 0)

print(f"\n=== {passed}/{passed+failed} ===\n")
sys.exit(0 if failed == 0 else 1)
