#!/usr/bin/env python3
"""
test_journal.py — Test suite para A1: Journal Control Block.

Valida todas las operaciones del control block MSM→Lumen:
  - Inicialización idempotente
  - Incremento de métricas (SETs/KILLs/writes)
  - Flags (add/remove/toggle)
  - Multi-file (create/status/close)
  - Integridad de ^CHANGES original
  - JSTAT display

Ejecutar: python test_journal.py

Author: Hermes + CadencesLab (Sprint A1)
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import _paths  # noqa: F401  # sys.path del stack PDB

from pdb_journal import (
    jrnl_init, jrnl_control, jrnl_incr, jrnl_status,
    jrnl_set_flag, jrnl_file_create, jrnl_file_status
)
from pdb_tools import tool_order, tool_get

PASS = FAIL = 0

def t(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} — {detail}")

print("🧪 TEST SUITE — A1: Journal Control Block")
print("=" * 50)

# ── 1. Inicialización ──
print("\n── 1. Inicialización ──")
r1 = jrnl_init()
t("Init idempotente", "already" in str(r1) or r1.get("success"))

ctrl = jrnl_control()
t("Control block existe", ctrl is not None)
t("Status = open", ctrl and ctrl.get("status") == "open")
t("Campos requeridos", ctrl and all(k in ctrl for k in ["status","seq_no","total_SETs","total_KILLs","flags"]))

# ── 2. Métricas ──
print("\n── 2. Métricas (SET/KILL/WRITES) ──")
old_sets = ctrl.get("total_SETs", 0)
old_seq = ctrl.get("seq_no", 0)
jrnl_incr("SET")
ctrl2 = jrnl_control()
t("SET incrementa total_SETs", ctrl2.get("total_SETs") == old_sets + 1)
t("SET incrementa seq_no", ctrl2.get("seq_no") == old_seq + 1)

old_kills = ctrl2.get("total_KILLs", 0)
jrnl_incr("KILL")
ctrl3 = jrnl_control()
t("KILL incrementa total_KILLs", ctrl3.get("total_KILLs") == old_kills + 1)
t("KILL incrementa seq_no", ctrl3.get("seq_no") == old_seq + 2)

# Writes: cada 10 ops → full, resto → partial
writes_before = ctrl3.get("full_writes", 0) + ctrl3.get("partial_writes", 0)
for i in range(15):
    jrnl_incr("SET")
ctrl4 = jrnl_control()
writes_after = ctrl4.get("full_writes", 0) + ctrl4.get("partial_writes", 0)
t("Writes incrementan", writes_after > writes_before)
t("Full writes > 0", ctrl4.get("full_writes", 0) > 0)
t("Partial writes > 0", ctrl4.get("partial_writes", 0) > 0)

# ── 3. Flags ──
print("\n── 3. Flags (MSM jflag) ──")
jrnl_set_flag("DAEMON_ACTIVE", True)
c = jrnl_control()
t("Flag DAEMON_ACTIVE ON", "DAEMON_ACTIVE" in c.get("flags", []))

jrnl_set_flag("DAEMON_ACTIVE", False)
c = jrnl_control()
t("Flag DAEMON_ACTIVE OFF", "DAEMON_ACTIVE" not in c.get("flags", []))

jrnl_set_flag("FORCE_JRNL_EOF", True)
jrnl_set_flag("GOT_NEXT_JRNL", True)
c = jrnl_control()
t("Múltiples flags", len(c.get("flags", [])) >= 3)

# ── 4. Multi-file ──
print("\n── 4. Multi-file (MSM: ^SYS(JOURNAL,index)) ──")
r = jrnl_file_create("test_suite_001.jsonl", "A")
t("File create", r.get("success"))

# Verificar que el archivo se guardó en ^CHANGES
file_entry = tool_get({"ns": "CHANGES", "subs": ["file", r.get("seq", 0)]})
t("File en ^CHANGES", file_entry.get("success") and file_entry.get("value") is not None)
if file_entry.get("value"):
    t("File status=O (open)", file_entry["value"].get("status") == "O")
    t("File type=A (auto)", file_entry["value"].get("type") == "A")

# Cerrar archivo
jrnl_file_status(r.get("seq", 0), "C")
f = tool_get({"ns": "CHANGES", "subs": ["file", r.get("seq", 0)]})
t("File closed (C)", f.get("value", {}).get("status") == "C")
t("File has closed timestamp", f.get("value", {}).get("closed") is not None)

# Archivo fixed
r_fix = jrnl_file_create("test_suite_002.jsonl", "F")
r2 = tool_get({"ns": "CHANGES", "subs": ["file", r_fix.get("seq", 0)]})
t("File type=F (fixed)", r2 and r2.get("value", {}).get("type") == "F")

# ── 5. Integridad ^CHANGES ──
print("\n── 5. Integridad ^CHANGES original ──")
r = tool_order({"ns": "CHANGES", "subs": [""], "direction": 1})
t("^CHANGES original accesible", r.get("success"))
t("^CHANGES tiene datos", r.get("value") is not None)

# ── 6. JSTAT display ──
print("\n── 6. JSTAT display ──")
status_text = jrnl_status()
t("JSTAT tiene título", "JOURNAL CONTROL BLOCK" in status_text)
t("JSTAT tiene métricas", "Total SETs" in status_text)
t("JSTAT tiene flags", "Flags" in status_text)
t("JSTAT tiene files", "File" in status_text or "test_suite" in status_text)

# ── RESULTADO ──
print(f"\n{'='*50}")
print(f"  RESULTADO: {PASS} OK / {FAIL} FAIL")
if FAIL == 0:
    print("  🎉 A1 validado — listo para A2")
else:
    print(f"  ⚠️  {FAIL} tests fallaron")
print(f"{'='*50}")
sys.exit(0 if FAIL == 0 else 1)
