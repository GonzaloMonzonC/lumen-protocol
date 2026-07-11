"""Tests CC2: Auto-Dream consolidation."""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from pdb_docs import _get_pdb_tools; t = _get_pdb_tools()

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS CC2: Auto-Dream\n')

# ── 1. Verificar estructura dream en edge ──
import os
dream_path = os.path.expanduser("~/Documents/GitHub/pdb-edge-worker/src/dream")
files = os.listdir(dream_path)
test("dream dir exists", os.path.isdir(dream_path))
test("consolidate.js exists", "consolidate.js" in files)
test("dreamLock.js exists", "dreamLock.js" in files)
test("scoring.js exists", "scoring.js" in files)
test("index.js exists", "index.js" in files)

# ── 2. Verificar scheduled handler en index.ts ──
idx_path = os.path.expanduser("~/Documents/GitHub/pdb-edge-worker/src/index.ts")
with open(idx_path) as f:
    idx = f.read()
test("scheduled handler in index.ts", "scheduled" in idx)
test("dream consolidation called", "consolidate" in idx)
test("dreamLock used", "dreamLock" in idx)
test("orient called", "orient" in idx)
test("gather called", "gather" in idx)

# ── 3. Verificar wrangler cron ──
wrangler_path = os.path.expanduser("~/Documents/GitHub/pdb-edge-worker/wrangler.toml")
with open(wrangler_path) as f:
    w = f.read()
test("cron schedule in wrangler", "[triggers]" in w or "cron" in w)

# ── 4. Simular datos para dream ──
# Crear learnings de prueba
for i in range(3):
    t.tool_set({"ns": "System", "subs": ["learnings", f"dream-test-{i}"], "value": {
        "fact": f"Test fact {i}", "category": "test", "confidence": 7
    }})

from pdb_tools import tool_order, tool_get
key = ""
dream_data = []
while True:
    r = tool_order({"ns": "System", "subs": ["learnings", key], "direction": -1})
    if not r.get("success") or r.get("value") is None: break
    key = r["value"]
    r2 = tool_get({"ns": "System", "subs": ["learnings", key]})
    if r2.get("success") and r2.get("value"):
        dream_data.append(r2["value"])
        if len(dream_data) >= 5: break

test("dream data exists", len(dream_data) > 0)

# ── 5. Scoring simulation ──
# Verificar que el scoring JS existe y tiene las funciones correctas
scoring_path = os.path.expanduser("~/Documents/GitHub/pdb-edge-worker/src/dream/scoring.js")
with open(scoring_path) as f:
    scoring = f.read()
test("computeRelevanceScore exported", "computeRelevanceScore" in scoring)
test("scoring uses frequency", "frequency" in scoring.lower() or "freq" in scoring.lower())
test("scoring uses recency", "recency" in scoring.lower() or "age" in scoring.lower() or "time" in scoring.lower())

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
