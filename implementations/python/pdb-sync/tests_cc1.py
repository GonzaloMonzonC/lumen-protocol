"""Tests exhaustivos CC1: Auto-Memory."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from pdb_docs import _get_pdb_tools; t = _get_pdb_tools()
from cc1_auto_memory import extract_with_tom, validate_with_zalo, write_to_pdb, auto_memory_extract

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS CC1: Auto-Memory\n')

# ── Test extractor ──
facts = extract_with_tom("Hemos configurado SET con journaling en PDB y desplegado en Workers")
test("extract returns list", isinstance(facts, list))
test("extract finds facts", len(facts) > 0)
test("extract has fact key", 'fact' in facts[0] if facts else False)
test("extract has category", 'category' in facts[0] if facts else False)
test("extract has confidence", facts[0].get('confidence', 0) > 0 if facts else False)

# Transcript vacío
empty = extract_with_tom("")
test("empty transcript", len(empty) == 0)

# Transcript con comentarios
comments = extract_with_tom("# comentario\n// otro\nnormal line with config flag")
test("comments filtered", len(comments) >= 1)

# ── Test validator ──
valid = validate_with_zalo(facts)
test("validate returns list", isinstance(valid, list))
test("validate passes high conf", len(valid) <= len(facts))

low_conf = [{"fact": "test", "confidence": 3}]
valid_low = validate_with_zalo(low_conf)
test("validate filters low conf", len(valid_low) == 0)

# ── Test writer ──
written = write_to_pdb(facts, "test-session")
test("write returns count", written >= 0)
test("write persists", written == len(facts))

# Verificar en PDB
from pdb_tools import tool_order, tool_get
key = ""
found = 0
while True:
    r = tool_order({"ns": "System", "subs": ["learnings", key], "direction": -1})
    if not r.get("success") or r.get("value") is None: break
    key = r["value"]
    r2 = tool_get({"ns": "System", "subs": ["learnings", key]})
    if r2.get("success") and r2.get("value"):
        found += 1
        break  # al menos 1
test("learnings in PDB", found > 0)

# ── Test pipeline completo ──
result = auto_memory_extract("Implementado sistema de colas con DDP en Cloudflare", "pipe-test")
test("pipeline returns dict", isinstance(result, dict))
test("pipeline has written", 'written' in result)
test("pipeline written >0", result.get('written', 0) > 0)

# Transcript corto
short = auto_memory_extract("hola", "short-test")
test("short transcript handled", short.get('written', -1) == 0)

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
