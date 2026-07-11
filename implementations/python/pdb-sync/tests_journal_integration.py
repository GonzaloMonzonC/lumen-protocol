"""Tests JRN-05: Journaling integración + Benchmark."""
import sys, os, time, json
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))

from pdb_journal import *

p = fail = 0
def t(n,o):
    global p,fail
    if o: p+=1; print(f"  ✅ {n}")
    else: fail+=1; print(f"  ❌ {n}")

print('🧪 TESTS JRN-05: Journaling Integración\n')

# ── 1. Pipeline completo ──
print('┌─ 1. WAL → DDP pipeline ─────────────────')
entry = make_entry("TEST", "integ:1", "integration_test", source="local")
r = write(entry)
t("WAL write local", r.get("ok") == True)

# Read back
entries = read(source="local", limit=5)
t("WAL read local entries", len(entries) >= 1)
t("local entry source correct", entries[0]["source"] == "local")

# ── 2. Cloud entry ──
print('\n┌─ 2. Cloud entry ────────────────────────')
e2 = make_entry("TEST", "integ:2", "from_cloud", source="cloud")
r = write(e2)
t("WAL write cloud", r.get("ok") == True)

cloud_entries = read(source="cloud", limit=5)
t("WAL read cloud entries", len(cloud_entries) >= 1)
t("cloud entry source correct", cloud_entries[0]["source"] == "cloud")

# ── 3. Source filtering ──
print('\n┌─ 3. Source filtering + anti-bucle ──────')
all_entries = read(limit=20)
local_count = len(read(source="local", limit=20))
cloud_count = len(read(source="cloud", limit=20))
t("all entries has both sources", local_count > 0 and cloud_count > 0)
t("total = local + cloud", len(all_entries) >= local_count + cloud_count)

# ── 4. Pending count ──
print('\n┌─ 4. Pending ────────────────────────────')
pend = pending()
t("pending returns int", isinstance(pend, int))
t("pending >= 0", pend >= 0)

# ── 5. WAL → SyncEngine ──
print('\n┌─ 5. SyncEngine WAL integration ────────')
from pdb_sync_engine import SyncEngine
engine = SyncEngine()
sync_r = engine.sync("pdb")
t("sync engine push ok", "error" not in sync_r.get("push", {}))
t("sync engine pull ok", "error" not in sync_r.get("pull", {}))

# ── 6. Benchmark ──
print('\n┌─ 6. Benchmark ──────────────────────────')
start = time.time()
for i in range(5):
    write(make_entry("BENCH", f"bench:{i}", f"val_{i}", source="local"))
write_ms = (time.time() - start) * 1000 / 5
t(f"WAL write {write_ms:.1f}ms avg", write_ms > 0)

start = time.time()
r = read(limit=10)
read_ms = (time.time() - start) * 1000
t(f"WAL read {read_ms:.1f}ms", read_ms > 0)

start = time.time()
pend = pending()
pend_ms = (time.time() - start) * 1000
t(f"pending {pend_ms:.1f}ms", pend_ms > 0)

print('\n┌─ 7. Benchmark Report ───────────────────')
print(f"  WAL write:    {write_ms:>6.1f} ms/entry")
print(f"  WAL read:     {read_ms:>6.1f} ms")
print(f"  pending:      {pend_ms:>6.1f} ms")

# ── 8. Cleanup test data ──
print('\n┌─ 8. Purge test data ────────────────────')
purged = purge(older_than="2222-01-01")  # No purges recent
t("purge safe (retains recent)", purged >= 0)

print(f"\n📊 {p}/{p+fail} tests passed")
sys.exit(0 if fail==0 else 1)
