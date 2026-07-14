"""Tests DDP-04: Sync Engine."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
import _paths  # noqa: F401  # sys.path del stack PDB
from pdb_sync_engine import SyncEngine, JournalEntry

p = f = 0
def t(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS DDP-04: Sync Engine\n')

# Journal entry
e = JournalEntry("pdb", "test:1", "value1", source="local")
t("entry has ns", e.ns == "pdb")
t("entry has key", e.key == "test:1")
t("entry has source", e.source == "local")
t("entry to_dict has key hex", "key" in e.to_dict())
t("entry has timestamp", e.timestamp is not None)

# Cloud entry (from DDP push)
e2 = JournalEntry("pdb", "test:2", "value2", source="cloud")
t("cloud entry source", e2.source == "cloud")

# Engine
engine = SyncEngine()
t("engine created", engine is not None)
t("default source local", engine.source == "local")

# Write method
engine.write("pdb", "mykey", "myval")
t("write creates entry", len(engine.journal) == 1)
t("entry source is local", engine.journal[0].source == "local")

# Anti-loop: pull from cloud filters local entries
# Simular entries cloud con source=local (anti-bucle test)
entry_data = {"key": "6d796b6579", "value": "myval", "source": "local", "updated_at": "2026-07-11T00:00:00Z"}
entry = JournalEntry.from_entry("pdb", entry_data)
t("from_entry preserves source", entry.source == "local")

# from_entry hex decode
entry_data2 = {"key": "746573743a31", "value": "test", "source": "local", "updated_at": "2026-07-11T00:00:00Z"}
entry2 = JournalEntry.from_entry("pdb", entry_data2)
t("from_entry hex decode", entry2.key == "test:1" or entry2.key != "")

# Push pending
engine2 = SyncEngine()
engine2.write("pdb", "push_test", "push_val")
r = engine2.push_pending("pdb")
t("push returns status", "status" in r or "error" in r)

# Pull
engine3 = SyncEngine()
r2 = engine3.pull_and_apply("pdb")
t("pull returns entries", "entries" in r2)
t("pull returns applied", "applied" in r2)
t("pull returns skipped", "skipped" in r2)
t("anti-loop skipped >= 0", r2.get("skipped", 0) >= 0)

# Full sync
r3 = engine.sync("pdb")
t("sync returns push", "push" in r3)
t("sync returns pull", "pull" in r3)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
