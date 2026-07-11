"""Tests MREPL v4: MSMSHELL — toggle, paging, errors."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
from mrepl import MREPL

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS MREPL v4\n')

r = MREPL()
r2 = MREPL(debug=True)
r3 = MREPL(context="TEST")

# Prompt variants
test("> prompt", r.prompt == "> ")
test("DEBUG> prompt", "DEBUG" in r2.prompt)
test("[ctx] prompt", "TEST" in r3.prompt)

# Toggle
r.exec("toggle")
test("toggle to D>", r.prompt.startswith("D"))
r.exec("toggle")
test("toggle back >", r.prompt == "> ")

# Commands
test("empty", r.exec("") == "")
test("exit stops", r.exec("exit") == "")

# History
r.exec("S x=1")
test("! recall", r.exec("!") is not None)
test("?? shows", "S x=1" in r.exec("??"))

# Help
h = r.exec("?")
test("? has $O", "$O" in h)
test("? has toggle", "toggle" in h)

# Error format
r4 = MREPL()
e = r4.exec("BADVAR")
test("error returns something", e is not None)

# Debug
test("debug on", "ON" in r.exec("debug"))
test("debug off", "OFF" in r.exec("debug"))

# Context changes prompt
r5 = MREPL(context="CHANGES")
test("CHANGES context", r5.prompt == "[CHANGES] > ")

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
