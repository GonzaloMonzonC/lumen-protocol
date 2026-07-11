"""Tests MREPL v7: INIT/EXIT, safe mode, $ZREF."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
from mrepl import MREPL

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS MREPL v7\n')

r = MREPL()
r2 = MREPL(debug=True)
r3 = MREPL(context="TEST")

# Prompts
test("> prompt", r.prompt == "> ")
test("DEBUG> prompt", "DEBUG" in r2.prompt)
test("[ctx] prompt", "TEST" in r3.prompt)

# Toggle
r.exec("toggle")
test("toggle D>", r.prompt.startswith("D"))
r.exec("toggle")

# Commands
test("empty", r.exec("") == "")
test("exit stops", r.exec("exit") == "")

# $ZREF
r.exec("$O(^TEST(\"\"))")
test("zref stored", r.last_zref is not None)

# Alias
a = r.exec("o TEST(\"\")")
test("alias works", a is not None)

# Help
test("? contains help", "?" in r.exec("?"))
test("?$O", "$O" in r.exec("?$O"))
test("?F", "FOR" in r.exec("?F"))
test("??", isinstance(r.exec("??"), str))

# Recall
r.exec("S x=1")
test("! recall", r.exec("!") is not None)

# Debug
test("debug on", "ON" in r.exec("debug"))
test("debug off", "OFF" in r.exec("debug"))

# Safe mode detection
r4 = MREPL()
test("safe mode off at start", not r4.safe_mode)

fallback = r4._get_tools()
test("tools available", fallback is not None)

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
