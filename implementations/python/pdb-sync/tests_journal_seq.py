#!/usr/bin/env python3
"""Tests Fase 2: journal con seq monótono, cursores y migración legacy."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: F401  # sys.path del stack PDB
from pdb_journal import (make_entry, write, read, purge, cursor_get, cursor_set,
                         read_after_cursor, last_seq, migrate_legacy,
                         JOURNAL_NS, JOURNAL_SUB)
from pdb_tools import tool_set, tool_kill

p = f = 0
def t(n, o):
    global p, f
    if o: p += 1; print(f"  ✅ {n}")
    else: f += 1; print(f"  ❌ {n}")

print('🧪 TESTS JRN-SEQ: journal seq monótono (Fase 2)\n')

# Aislar: limpiar journal y cursores de runs previos
purge()
cursor_set("push", last_seq())
base_seq = last_seq()

# 1. Colisión de timestamp: mismo ts, misma key → v1 sobreescribía, v2 no
e1 = make_entry("T", "k", "v1"); e2 = make_entry("T", "k", "v2")
e2["ts"] = e1["ts"]  # forzar mismo timestamp
r1, r2 = write(e1), write(e2)
t("seqs distintos con mismo ts", r1["seq"] != r2["seq"])
t("seq crece monótono", r2["seq"] == r1["seq"] + 1)
entries = read(since=base_seq, limit=10)
t("ambas entries sobreviven", len(entries) == 2)
t("orden total por seq", [e["value"] for e in entries] == ["v1", "v2"])

# 2. Cursor: push incremental
pend = read_after_cursor("push", source="local")
t("pendientes tras cursor base", len(pend) == 2)
cursor_set("push", pend[-1]["seq"])
t("cursor avanzado", cursor_get("push") == r2["seq"])
t("nada pendiente tras avance", len(read_after_cursor("push", source="local")) == 0)
w3 = write(make_entry("T", "k3", "v3"))
t("nuevo entry sí pendiente",
  [e["seq"] for e in read_after_cursor("push", source="local")] == [w3["seq"]])

# 3. Migración legacy: sembrar forma v1 a mano
tool_set({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, "2026-07-01T00:00:00", "OLD", "a"],
          "value": json.dumps({"value": "legacy-a", "source": "local", "op": "set"})})
tool_set({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, "2026-07-02T00:00:00", "OLD", "b"],
          "value": json.dumps({"value": "legacy-b", "source": "local", "op": "set"})})
n = migrate_legacy()
t("migradas 2 legacy", n == 2)
allE = read(since=base_seq, limit=20)
t("total 5 entries tras migrar", len(allE) == 5)
t("legacy re-encoladas en orden ts", [e["value"] for e in allE[-2:]] == ["legacy-a", "legacy-b"])
t("legacy conservan ts original", allE[-2]["ts"] == "2026-07-01T00:00:00")
t("migrate idempotente", migrate_legacy() == 0)

# 4. Purge por seq
n = purge(up_to_seq=r2["seq"])
t("purge up_to_seq borra 2", n == 2)
t("quedan 3", len(read(since=base_seq, limit=20)) == 3)

# Limpieza
purge()

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f == 0 else 1)
