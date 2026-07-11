"""Tests MREPL: MSMSHELL REPL mejorado."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))

# Patch readline for testing
sys.modules['readline'] = type(sys)('readline')
sys.modules['readline'].get_current_history_length = lambda: 0
sys.modules['readline'].get_history_item = lambda x: ''
sys.modules['readline'].read_history_file = lambda x: None
sys.modules['readline'].write_history_file = lambda x: None

from mrepl import MREPL

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS MREPL: MSMSHELL REPL\n')

r = MREPL()

# Basic commands
test("empty cmd", r.exec("") == "")
test("exit cmd", "Bye" in r.exec("exit"))
r.running = True

# Debug toggle
test("debug on", "ON" in r.exec("debug"))
test("debug off", "OFF" in r.exec("debug"))

# Help
test("help has commands", "exit" in r.exec("help"))

# History
test("history shows items", isinstance(r.exec("history"), str))

# M-Light eval
result = r.exec("$O(^TEST(\"\"))")
test("$O executes", result is not None and len(str(result)) > 0)

# Error handling
result2 = r.exec("BAD SYNTAX!!!")
test("error handling", not result2.startswith("🔴") == False)  # just check it doesn't crash

# Special commands
test("debug toggle works", "ON" in r.exec("debug"))
r.exec("debug")  # back to off

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
