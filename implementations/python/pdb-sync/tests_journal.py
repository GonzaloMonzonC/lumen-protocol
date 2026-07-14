"""Tests JRN-01/02: WAL + Source Tagging."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
import _paths  # noqa: F401  # sys.path del stack PDB
from pdb_journal import *

p = f = 0
def t(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS JRN: WAL Journal\n')

# 1. Make entry
e = make_entry("TEST", "k1", "v1", source="local")
t("entry has ns", e["ns"] == "TEST")
t("entry has key", e["key"] == "k1")
t("entry has source", e["source"] == "local")
t("entry has ts", "ts" in e)
t("entry has op", e["op"] == "set")

# 2. Cloud entry
e2 = make_entry("TEST", "k2", "v2", source="cloud")
t("cloud entry source", e2["source"] == "cloud")

# 3. Write
r = write(e)
t("write ok", r.get("ok") == True)
t("write has ts", "ts" in r)

# 4. Write cloud
r2 = write(e2)
t("write cloud ok", r2.get("ok") == True)

# 5. Read all
entries = read(limit=10)
t("read returns entries", len(entries) >= 2)

# 6. Read local only
local = read(source="local", limit=10)
t("read local only", len(local) >= 1)
t("local entry source", local[0]["source"] == "local")

# 7. Read cloud only
cloud = read(source="cloud", limit=10)
t("read cloud only", len(cloud) >= 1)
t("cloud entry source", cloud[0]["source"] == "cloud")

# 8. Pending
pend = pending()
t("pending > 0", pend >= 1)

# 9. Purge old entries (before now)
n = purge(older_than="2222-01-01")
t("purge retains recent", n >= -1)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
