#!/usr/bin/env python3
"""
pdb_docs_test.py — Batería completa de tests para PDB Doc Engine.

Valida D1 (CRUD), D2 (TTL), D3 (Versionado), D4 (Git hooks),
D5 (M-code ejecutable), D6 (Cross-refs inversas).

Ejecutar: python pdb_docs_test.py

Author: Hermes + CadencesLab
Date: 2026-07-11
"""

import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from pdb_docs import (
    doc_set, doc_get, doc_order, doc_kill,
    doc_is_stale, doc_mark_stale, doc_touch,
    doc_history, doc_diff, doc_rollback,
    doc_exec,
    doc_add_link, doc_find_refs, doc_graph,
    get_doc_ttl, DOC_TTL,
    _get_pdb_tools
)

PASS = 0
FAIL = 0

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} — {detail}")

def section(title):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")

# ─────────────────────────────────────────────────────────────────────
# D1: CRUD
# ─────────────────────────────────────────────────────────────────────

section("D1: CRUD (SET/GET/ORDER/KILL)")

doc_set("test", ["d1", "crud"], {"content": "hello world", "confidence": 9, "source_agent": "test"})
d = doc_get("test", ["d1", "crud"])
test("SET + GET", d and d["content"] == "hello world")

k = doc_order("test", ["d1", ""])
test("$ORDER first", k == "crud")

doc_kill("test", ["d1", "crud"])
d2 = doc_get("test", ["d1", "crud"])
test("KILL + GET null", d2 is None)

# ─────────────────────────────────────────────────────────────────────
# D2: TTL
# ─────────────────────────────────────────────────────────────────────

section("D2: TTL + stale + touch")

test("TTL api = 3600s", get_doc_ttl("api") == 3600)
test("TTL playbook = ∞", get_doc_ttl("playbook") is None)
test("TTL default = 604800s", get_doc_ttl("unknown") == 604800)

doc_set("api", ["d2", "fresh"], {"content": "fresh", "confidence": 5, "source_agent": "test"})
test("doc NOT stale (just created)", not doc_is_stale("api", ["d2", "fresh"]))

doc_set("api", ["d2", "old"], {"content": "old", "confidence": 5, "source_agent": "test", "updated_at": "2020-01-01T00:00:00Z"})
test("doc IS stale (4 years old)", doc_is_stale("api", ["d2", "old"]))

doc_touch("api", ["d2", "old"])
d = doc_get("api", ["d2", "old"])
test("touch resets read_count", d and d.get("read_count") == 1)
test("touch resets stale flag", d and d.get("stale") is False)

# ─────────────────────────────────────────────────────────────────────
# D3: Versionado
# ─────────────────────────────────────────────────────────────────────

section("D3: Versionado (history/diff/rollback)")

doc_set("test", ["d3", "ver"], {"content": "v1", "confidence": 5, "source_agent": "test"})
doc_set("test", ["d3", "ver"], {"content": "v2", "confidence": 7, "source_agent": "test"})
doc_set("test", ["d3", "ver"], {"content": "v3", "confidence": 9, "source_agent": "test"})

h = doc_history("test", ["d3", "ver"], limit=5)
test("history has versions", len(h) >= 1)

d = doc_diff("test", ["d3", "ver"])
test("diff current vs current: no change", d.get("changed") is False)

# Rollback a la primera versión del historial
if h:
    rb = doc_rollback("test", ["d3", "ver"], h[0]["timestamp"])
    test("rollback success", rb.get("success") is True)
    current = doc_get("test", ["d3", "ver"])
    test("rollback restored old content", current and "v2" in str(current.get("content", "")))

# ─────────────────────────────────────────────────────────────────────
# D4: Git hooks
# ─────────────────────────────────────────────────────────────────────

section("D4: Git hooks (estructura)")

hook_path = os.path.join(os.path.dirname(__file__), "pdb_docs_git_hook.py")
test("hook file exists", os.path.exists(hook_path))

# ─────────────────────────────────────────────────────────────────────
# D5: M-code ejecutable
# ─────────────────────────────────────────────────────────────────────

section("D5: M-code ejecutable (KILL FEATURE)")

# Preparar datos
tools = _get_pdb_tools()
tools.tool_set({"ns": "TEST_D5", "subs": ["A"], "value": "alpha"})
tools.tool_set({"ns": "TEST_D5", "subs": ["B"], "value": "beta"})
tools.tool_set({"ns": "TEST_D5", "subs": ["Z"], "value": "zeta"})

# Test $ORDER
doc_set("playbook", ["d5", "order"], {"content": "$O(^TEST_D5(\"\"))", "confidence": 10, "source_agent": "test", "executable": True})
d = doc_get("playbook", ["d5", "order"])
test("$ORDER returns first key", d and d.get("_live_data") == "A")
test("_executed flag", d and d.get("_executed") is True)

# Test $GET
doc_set("playbook", ["d5", "get"], {"content": "$G(^TEST_D5(\"B\"))", "confidence": 10, "source_agent": "test", "executable": True})
d = doc_get("playbook", ["d5", "get"])
test("$GET returns value", d and d.get("_live_data") == "beta")

# Test doc_exec explícito
r = doc_exec("playbook", ["d5", "order"])
test("doc_exec success", r.get("success") is True)
test("doc_exec result", r.get("result") == "A")

# Test doc no ejecutable
doc_set("api", ["d5", "normal"], {"content": "just docs", "confidence": 5, "source_agent": "test"})
d = doc_get("api", ["d5", "normal"])
test("non-executable: no _executed", d and d.get("_executed") is None)

# ─────────────────────────────────────────────────────────────────────
# D6: Cross-refs
# ─────────────────────────────────────────────────────────────────────

section("D6: Cross-refs inversas")

doc_set("architecture", ["d6", "main"], {"content": "main arch doc", "confidence": 9, "source_agent": "test", "links": ["^decisions:99"]})
doc_set("api", ["d6", "ref"], {"content": "api doc", "confidence": 8, "source_agent": "test", "links": ["^decisions:99", "^learnings:1"]})

doc_add_link("api", ["d6", "ref"], "^patterns:7")
d = doc_get("api", ["d6", "ref"])
test("add_link appends", d and "^patterns:7" in d.get("links", []))

refs = doc_find_refs("^decisions:99")
test("find_refs finds docs", len(refs) >= 1)

g = doc_graph("architecture", ["d6", "main"])
test("graph center", g.get("center") is not None)
test("graph has links_out", len(g.get("links_out", [])) >= 1)

# ─────────────────────────────────────────────────────────────────────
# RESULTADO
# ─────────────────────────────────────────────────────────────────────

section(f"RESULTADO: {PASS} OK / {FAIL} FAIL")

if FAIL == 0:
    print("\n  🎉 TODOS LOS TESTS PASARON — PDB Doc Engine validado\n")
else:
    print(f"\n  ⚠️  {FAIL} tests fallaron — revisar\n")

sys.exit(0 if FAIL == 0 else 1)
