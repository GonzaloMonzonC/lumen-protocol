"""Tests MREPL v6."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
from mrepl import MREPL

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS MREPL v6\n')

r = MREPL()
r2 = MREPL(debug=True)

test("> prompt", ">" in r.prompt)
test("DEBUG in prompt", "DEBUG" in r2.prompt)
r.exec("toggle")
test("toggle D>", "D>" in r.prompt)
r.exec("toggle")
test("empty", r.exec("") == "")
test("exit stops", r.exec("exit") == "")

# Help by topic
h = r.exec("?$O")
test("?$O gives help", "$O" in h)
h2 = r.exec("?FOR")
test("?FOR gives help", "FOR" in h2)

# % last result
r.exec('W "test"')
test("% exists", hasattr(r, 'last_result'))

# History
r.exec("S y=1")
test("! recall", r.exec("!") is not None)
test("?? shows", "S y=1" in r.exec("??"))

# General help
h4 = r.exec("?")
test("? has help", "?" in h4)

# Debug
test("debug on", "ON" in r.exec("debug"))
test("debug off", "OFF" in r.exec("debug"))

# Error
r5 = MREPL()
test("error returns str", isinstance(r5.exec("BADVAR"), str))

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
