#!/usr/bin/env python3
"""Test Sprint A2-A4: Multi-file, Recovery, DDP Bridge."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import _paths  # noqa: F401  # sys.path del stack PDB
from pdb_tools import tool_set
from pdb_journal import *

PASS = FAIL = 0
def t(n, c, d=""):
    global PASS, FAIL
    if c: PASS += 1; print(f"  ✅ {n}")
    else: FAIL += 1; print(f"  ❌ {n} — {d}")

print("🧪 TEST A2-A4 — Multi-file + Recovery + DDP Bridge")
print("=" * 50)

# A2: Multi-file
print("\n── A2: Multi-file ──")
af = jrnl_active_file()
t("Active file exists", af and af.get("seq") is not None)
t("Status = O", af and af["data"].get("status") == "O")

jrnl_file_status(af["seq"], "F")
af2 = jrnl_active_file()
t("Rotation creates new file", af2["seq"] != af["seq"])
t("New file status = O", af2["data"].get("status") == "O")

for i in range(5):
    jrnl_incr("SET")
ctrl = jrnl_control()
t("Incr after rotation", ctrl and ctrl.get("seq_no", 0) > 0)

# A3: Recovery
print("\n── A3: Recovery VERIFY ──")
from pdb_tools import tool_set
tool_set({"ns": "_TEST", "subs": ["verify"], "value": "v1"})
v = jrnl_verify_entry({"op": "SET", "ns": "_TEST", "subs": ["verify"], "timestamp": "2026-07-11T12:00:00Z"})
t("Entry valid", v["valid"])
v2 = jrnl_verify_entry({"op": "SET", "ns": "_TEST"})
t("Entry invalid (missing subs)", not v2["valid"])
v3 = jrnl_verify_precondition({"op": "SET", "ns": "_TEST", "subs": ["verify"], "old_value": "v1", "new_value": "v2"})
t("Precondition OK", v3["valid"])
v4 = jrnl_verify_precondition({"op": "SET", "ns": "_TEST", "subs": ["verify"], "old_value": "wrong"})
t("Precondition conflict", not v4["valid"])

# A4: DDP Bridge
print("\n── A4: DDP Bridge ──")
tool_set({"ns":"CHANGES","subs":["control"],"value":{"status":"open","seq_no":0,"total_SETs":0,"total_KILLs":0,"full_writes":0,"partial_writes":0,"out_seq":0,"last_checkpoint":"2026-01-01T00:00:00","flags":["AUTO_GEN"]}})
jrnl_mark_dirty()
t("Dirty flag ON", jrnl_is_dirty())
jrnl_buffer_push("edge", {"ns": "T", "subs": ["x"], "op": "SET", "value": 1})
jrnl_buffer_push("edge", {"ns": "T", "subs": ["y"], "op": "SET", "value": 2})
ops = jrnl_buffer_flush("edge")
t("Buffer has 2 ops", len(ops) == 2)
r = jrnl_sync_bridge()
t("Sync dirty→clean", r["synced"] > 0)
t("Dirty flag OFF after sync", not jrnl_is_dirty())

# JSTAT
print("\n── JSTAT Display ──")
status = jrnl_status()
t("Has control block", "JOURNAL CONTROL BLOCK" in status)
t("Has metrics", "Total SETs" in status)
t("Has files", "File" in status)

print(f"\n{'='*50}")
print(f"  A2-A4: {PASS} OK / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
