"""Tests MREPL v8: Pages, NOMEM, +/-, zref."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
from mrepl import MREPL

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS MREPL v8\n')

r = MREPL()
r2 = MREPL(debug=True)
r3 = MREPL(context="System")

# Prompts
test("> prompt", r.prompt == "> ")
test("DEBUG prompt", "DEBUG" in r2.prompt)
test("[ctx] prompt", "System" in r3.prompt)

# Toggle
r.exec("toggle")
test("D> prompt", r.prompt.startswith("D"))
r.exec("toggle")

# Commands
test("empty", r.exec("") == "")
test("exit", r.exec("exit") == "")

# $ZREF
r.exec("$O(^TEST(\"\"))")
test("zref stored", r.last_zref is not None)

# Alias
test("alias o", r.exec("o TEST(\"\")") is not None)

# History pages
r.exec("S x=1")
r.exec("S x=2")
test("+ page up", isinstance(r.exec("+"), str))
test("- page down", isinstance(r.exec("-"), str))

# Help
test("? general", "?" in r.exec("?"))
test("?? last 10", isinstance(r.exec("??"), str))
test("?$O help", "$O" in r.exec("?$O"))
test("?5 from N", isinstance(r.exec("?1"), str))

# Debug
test("debug on", "ON" in r.exec("debug"))
test("debug off", "OFF" in r.exec("debug"))

# Recall
r.exec("S x=99")
test("! recall", r.exec("!") is not None)

# NOMEM
test("!nomem", "NOMEM" in r.exec("nomem"))
test("safe mode", r.safe_mode)
r.exec("safe")

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
