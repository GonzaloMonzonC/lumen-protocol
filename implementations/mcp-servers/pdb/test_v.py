"""Test V write through M-Light - final"""
import sys
sys.path.insert(0, '.')
from m_light import MEvaluator

e = MEvaluator()
ok = True

def check(label, actual, expected):
    global ok
    if actual == expected:
        print(f'  ✓ {label} = {actual}')
    else:
        print(f'  ✗ {label} = {actual} (expected {expected})')
        ok = False

print("=== $V() READ TESTS ===")
check('$V(2,-4,2)', e.eval_expr('$V(2,-4,2)'), 8)
check('$V(0,-4,2)', e.eval_expr('$V(0,-4,2)'), 11)
check('$V(121,-4,1)', e.eval_expr('$V(121,-4,1)'), 0)
check('$V(18,-5)', e.eval_expr('$V(18,-5)'), 0)
check('$V(44,$J,2)', e.eval_expr('$V(44,$J,2)'), 0)

print()
print("=== V (SET $V) WRITE TESTS ===")
e.eval('V 108:$J:51200:4')
check('$V(108,$J,4) after V 108:$J:51200:4', e.eval_expr('$V(108,$J,4)'), 51200)

e.eval('V 50:0:255:1')
check('$V(50,0,1) after V 50:0:255:1', e.eval_expr('$V(50,0,1)'), 255)

e.eval('V 100:-4:42:1')
check('$V(100,-4,1) after V 100:-4:42:1', e.eval_expr('$V(100,-4,1)'), 42)

e.eval('V 200:0:65535:2')
check('$V(200,0,2) after V 200:0:65535:2', e.eval_expr('$V(200,0,2)'), 65535)

# Test default size=1
e.eval('V 10:$J:99')
check('$V(10,$J) after V 10:$J:99 (default size=1)', e.eval_expr('$V(10,$J)'), 99)

print()
print("=== $ZB() BIT FIELD TESTS ===")
check('$ZB(8,1,7)', e.eval_expr('$ZB(8,1,7)'), 4)
check('$ZB(11,16,1)', e.eval_expr('$ZB(11,16,1)'), 0)
check('$ZB(255,0,4)', e.eval_expr('$ZB(255,0,4)'), 15)
check('$ZB(255,4,4)', e.eval_expr('$ZB(255,4,4)'), 15)
check('$ZB(#FFFF,12,4)', e.eval_expr('$ZB(#FFFF,12,4)'), 15)
check('$ZB($V(2,-4,2),#1,7)', e.eval_expr('$ZB($V(2,-4,2),#1,7)'), 4)
check('$ZB($V(0,-4,2),#40,7)', e.eval_expr('$ZB($V(0,-4,2),#40,7)'), 0)

print()
if ok:
    print("=== ALL TESTS PASSED! ===")
else:
    print("=== SOME TESTS FAILED! ===")
