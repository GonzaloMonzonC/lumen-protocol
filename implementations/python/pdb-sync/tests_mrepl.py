"""Tests MREPL v2: MSMSHELL-style REPL."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
from mrepl import MREPL

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS MREPL v2: MSMSHELL\n')

r = MREPL()

# Prompt
test("normal prompt", r.prompt == "> ")
r2 = MREPL(debug=True)
test("debug prompt", "DEBUG>" in r2.prompt)
r3 = MREPL(context="TEST")
test("context prompt", "[TEST]" in r3.prompt)

# Commands
test("empty cmd", r.exec("") == "")
test("exit stops", "Bye" not in r.exec("exit"))
r.running = True

# Debug toggle
test("debug on", "ON" in r.exec("debug"))
test("debug off", "OFF" in r.exec("debug"))

# History (!, !N, ??)
r.exec("S x=1")
result = r.exec("!")
test("! recall", result is not None)
result2 = r.exec("!1")
test("!1 recall", result2 is not None)

test("?? shows history", "S x=1" in r.exec("??"))

# Help
test("? has help", "$O" in r.exec("?"))
test("? has debug", "debug" in r.exec("?"))

# M-Light eval
result = r.exec("$O(^TEST(\"\"))")
test("$O executes", result is not None and len(str(result)) > 0)

# Non-existent recall
test("!999 error", "Not found" in r.exec("!999"))

# Context changes prompt
r4 = MREPL(context="System")
test("System context", r4.prompt == "[System] > ")

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
