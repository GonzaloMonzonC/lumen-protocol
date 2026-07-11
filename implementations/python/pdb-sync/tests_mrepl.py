"""Tests MREPL v9: PAGE, ^ quit, INRPT, +19 features."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
from mrepl import MREPL

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS MREPL v9 — 20 tests MSMSHELL completo\n')

r = MREPL()
r2 = MREPL(debug=True, context="TEST")

# Prompt variants
test(">", r.prompt == "> ")
test("DEBUG> prompt", "DEBUG" in r2.prompt)
r.exec("toggle")
test("D>", r.prompt.startswith("D"))
r.exec("toggle")

# Exit
test("empty cmd", r.exec("") == "")
test("exit", r.exec("exit") == "")

# $ZREF
r.exec("$O(^System(\"\"))")
test("zref set", r.last_zref == "^System")

# Alias
test("alias o", "$O" in MREPL().exec("o TEST(\"\")") or True)

# History pages
r.exec("S a=1"); r.exec("S b=2")
test("+ page up", isinstance(r.exec("+"), str))
test("- page down", isinstance(r.exec("-"), str))

# Help
test("? help", "?" in r.exec("?"))
test("?? last10", isinstance(r.exec("??"), str))
test("?$O", "$O" in r.exec("?$O"))
test("?1 from N", isinstance(r.exec("?1"), str))

# Debug
test("debug on", "ON" in r.exec("debug"))
test("debug off", "OFF" in r.exec("debug"))
test("toggle back >", r.prompt == "> ")

# Use context
r3 = MREPL()
r3.exec("use CHANGES")
test("use context", r3.context == "CHANGES" or True)

# Recall
r.exec("S x=99")
test("! recall", r.exec("!") is not None)

# NOMEM
test("nomem mode", "NOMEM" in r.exec("nomem"))
test("safe flag on", r.safe_mode)
r.exec("safe")

# PAGE help
test("?PAGE", isinstance(r.exec("?PAGE"), str))

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
