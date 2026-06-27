"""OBJ-5 Test: I/O Operations"""
import sys, os
sys.path.insert(0, os.path.abspath('.'))
from m_light import MEvaluator

print('=== OBJ-5: I/O Operations ===')
print()

# W *n - WRITE ASCII (bell)
m = MEvaluator()
print('--- W *7 (bell) ---')
m.eval('W *7')
print('✅ W *7')

# W ! (newline)
print('--- W !! (two newlines) ---')
m.eval('W !')
print('✅ W !')

# W "text" (string)
print('--- W "Hello" ---')
m.eval('W "Hello"')
print('✅ W "Hello"')

# Comma-separated WRITE: W *7,!!,"text"
print('--- MSM STU: W *7,!!,"STU can not be run twice!" ---')
m.eval('W *7,!!,"STU can not be run twice!"')
print('✅ W *7,!!,"text"')

# W with variable
print('--- W with variable ---')
m.eval('S X="MSM" W X')
print('✅ W X')

# R (READ)
print('--- R !!,"Enter name: ",X ---')
m.eval('R !!,"Enter name: ",X')
print(f'✅ R prompt: X={m.scope.get("X")!r} (should be empty string)')

# MSM STU pattern: W !!?5,"Enter..."
print('--- MSM: W !!?5,"Enter Y to continue" ---')
m.eval('W !!?5,"Enter Y or N"')
print('✅ W !!?5,"text"')

# Full MSM dialogs
print()
print('=== MSM STU Dialog Simulation ===')
script = """
S CONFIG="DEFAULT"
W !!,"Enter startup configuration <",CONFIG
R "> ",R
I R="" S R=CONFIG W R
Q
"""
m2 = MEvaluator()
m2.eval_script(script)
print(f'✅ MSM dialog: CONFIG={m2.scope.get("CONFIG")!r}, R={m2.scope.get("R")!r}')

print()
print('✅ OBJ-5: I/O Operations completas!')
