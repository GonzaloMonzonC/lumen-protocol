"""Tests M-Light Error Handler (MSM FUN_0043eac0 pattern)."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from m_light_errors import *

p = f = 0
def test(name, ok):
    global p, f
    if ok: p+=1; print(f"  ✅ {name}")
    else: f+=1; print(f"  ❌ {name}")

print('🧪 TESTS Error Handler\n')

h = MLErrorHandler("test")

# Basic error
r = h.error("test error", ERROR)
test("error returns True for ERROR", r)
test("count incremented", h.counts[ERROR] == 1)

# Warning
r2 = h.error("test warning", WARNING)
test("warning returns False", not r2)
test("warning count", h.counts[WARNING] == 1)

# Context
h2 = MLErrorHandler("ctx_test")
h2.set_context(op="SET", ns="TEST")
r3 = h2.error("context error", ERROR)
test("context set", h2.context.get("op") == "SET")

# Threshold
h3 = MLErrorHandler("threshold_test", thresholds={ERROR: 3})
h3.error("e1", ERROR); h3.error("e2", ERROR)
test("under threshold", not h3.halted)
h3.error("e3", ERROR)
test("threshold reached", h3.halted)

# Callback
cb_calls = []
def cb(msg, level, ctx):
    cb_calls.append((msg, level))
h4 = MLErrorHandler("cb_test")
h4.on_error = cb
h4.error("cb error", WARNING)
test("callback called", len(cb_calls) == 1)
test("callback level", cb_calls[0][1] == WARNING)

# Reset
h5 = MLErrorHandler("reset_test")
h5.error("e1", ERROR)
h5.error("e2", FATAL)
h5.reset()
test("reset counters", h5.counts[FATAL] == 0 and h5.counts[ERROR] == 0)
test("reset halted", not h5.halted)

# Summary
h6 = MLErrorHandler("summary_test")
h6.error("e1", ERROR)
s = h6.summary()
test("summary has name", s.get("name") == "summary_test")
test("summary has counts", s["counts"].get(ERROR) >= 1)

# Fatal
h7 = MLErrorHandler("fatal_test")
h7.error("fatal!", FATAL)
test("fatal halts", h7.halted)

# Info
h8 = MLErrorHandler("info_test")
r9 = h8.error("info msg", INFO)
test("info returns False", not r9)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
