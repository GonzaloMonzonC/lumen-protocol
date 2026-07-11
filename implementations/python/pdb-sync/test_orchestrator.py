#!/usr/bin/env python3
"""Test Sprint C: Orquestador MVM."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdb_orchestrator import *

PASS = FAIL = 0
def t(n, c, d=""):
    global PASS, FAIL
    if c: PASS += 1; print(f"  ✅ {n}")
    else: FAIL += 1; print(f"  ❌ {n} — {d}")

print("🧪 TEST SPRINT C — Orquestador MVM")
print("=" * 40)

# Register
orch_register_agent("test_c1", "START^C1:00:00:1")
orch_register_agent("test_c2", "START^C2:00:00:1")

agents = orch_list_agents()
t("2 agents registered", len(agents) >= 2)
t("Agent has command", any(a["config"].get("command", "").startswith("START") for a in agents))

# M-code startup
r = orch_mvm_startup()
t("M-code startup success", r.get("success"))

# Active agents
active = orch_active_agents()
t("Active agents list returned", isinstance(active, list))

# Status display
status = orch_status()
t("Status has title", "ORQUESTADOR" in status)
t("Status shows agents", "test_c1" in status)

# M-code for docs
mcode = orch_mcode_status()
t("M-code expression", "$O" in mcode)

print(f"\n{'='*40}")
print(f"  Sprint C: {PASS} OK / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
