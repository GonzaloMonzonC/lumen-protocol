#!/usr/bin/env python3
"""Test Sprint B: DDP — HMAC + Nonce Concurrency."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdb_ddp import *

PASS = FAIL = 0
def t(n, c, d=""):
    global PASS, FAIL
    if c: PASS += 1; print(f"  ✅ {n}")
    else: FAIL += 1; print(f"  ❌ {n} — {d}")

print("🧪 TEST SPRINT B — DDP HMAC+Nonce")
print("=" * 40)

# Sign + Verify
op = ddp_sign_operation("test_agent", {"ns": "T", "op": "SET", "value": 42})
t("Sign returns agent", op.get("agent") == "test_agent")
t("Sign returns nonce > 0", op.get("nonce", 0) > 0)
t("Sign returns signature", len(op.get("sig", "")) == 16)

v = ddp_verify_operation(op)
t("Verify valid signature", v["valid"])

# Replay attack
v2 = ddp_verify_operation(op)
t("Replay blocked", not v2["valid"])
t("Replay reason = nonce", "nonce" in v2.get("reason", ""))

# Invalid signature
fake = dict(op)
fake["sig"] = "deadbeef00000000"
v3 = ddp_verify_operation(fake)
t("Fake signature blocked", not v3["valid"])

# Multi-agent nonces independent
op_a = ddp_sign_operation("agent_a", {"ns": "T", "op": "SET"})
op_b = ddp_sign_operation("agent_b", {"ns": "T", "op": "SET"})
t("Agent A nonce", op_a["nonce"] > 0)
t("Agent B nonce", op_b["nonce"] > 0)
va = ddp_verify_operation(op_a)
vb = ddp_verify_operation(op_b)
t("Both valid", va["valid"] and vb["valid"])

# Sequential operations
for i in range(3):
    op = ddp_sign_operation("seq_test", {"ns": "T", "op": "SET", "seq": i})
    v = ddp_verify_operation(op)
    t(f"Seq op {i} valid", v["valid"])

# Replay seq op 0
v_replay = ddp_verify_operation({"agent": "seq_test", "nonce": 1, "op": {}, "sig": "bad"})
t("Seq replay blocked", not v_replay["valid"])

# Link status
links = ddp_all_links()
t("Links list returned", isinstance(links, list))

print(f"\n{'='*40}")
print(f"  Sprint B: {PASS} OK / {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
