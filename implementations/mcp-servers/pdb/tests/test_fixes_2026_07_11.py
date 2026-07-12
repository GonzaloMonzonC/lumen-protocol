"""
test_fixes_2026_07_11.py — Tests para bugs recién arreglados en M-Light
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from m_light import MEvaluator
import pdb_tools

PASS = 0
FAIL = 0

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}: {detail}")

def fresh_enc():
    """Nuevo evaluador con estado limpio."""
    return MEvaluator(pdb_tools)

# ── Setup ──
pdb_tools.tool_set({"ns": "test", "subs": ["p1"], "value": "a^b^c"})
for name in ['alfa', 'beta', 'gamma']:
    pdb_tools.tool_set({"ns": "tfor", "subs": ["g1", name], "value": f"val_{name}"})

print("=== TEST 1: $P anidado con $G ===")
enc = fresh_enc()
r = enc.eval('$P($G(^test("p1")),"^",2)')
test("$P($G(...),...)", r == "b", f"got {repr(r)}")

print("\n=== TEST 2: $L con delimitador ===")
enc = fresh_enc()
r = enc.eval('$L("a#b#c","#")')
test("$L(val,'#') count", r == 3, f"got {repr(r)}")
r2 = enc.eval('$L("hello")')
test("$L simple", r2 == 5, f"got {repr(r2)}")

print("\n=== TEST 3: String literal con # ===")
enc = fresh_enc()
r = enc.eval('"a#b#c"')
test("string con #", r == "a#b#c", f"got {repr(r)}")
r2 = enc.eval('"#hash"')
test("string empezando con #", r2 == "#hash", f"got {repr(r2)}")

print("\n=== TEST 4: Multi-comando en línea ===")
enc = fresh_enc()
enc.scope.set('a', 0)
enc.scope.set('b', 0)
enc._exec_line('S a=1 S b=2')
test("S a=1 S b=2", enc.scope.get('a') == 1 and enc.scope.get('b') == 2,
     f"got a={enc.scope.get('a')} b={enc.scope.get('b')}")

enc = fresh_enc()
enc.scope.set('x', 0)
enc._exec_line('S x=x+1 W "ok"')
test("S + W en línea", enc.scope.get('x') == 1, f"got x={enc.scope.get('x')}")

print("\n=== TEST 5: Q:cond con postcond ===")
enc = fresh_enc()
enc.scope.set('n', 0)
enc._exec_line('Q:1=0  S n=n+1')
test("Q:false + S (n=1)", enc.scope.get('n') == 1, f"got n={enc.scope.get('n')}")

enc = fresh_enc()
enc.scope.set('n', 0)
enc._exec_line('Q:1=1  S n=n+1')
test("Q:true + S (n=0)", enc.scope.get('n') == 0, f"got n={enc.scope.get('n')}")

print("\n=== TEST 6: FOR + $ORDER (2 niveles) ===")
enc = fresh_enc()
enc.eval('S cnt=0,k=""')
enc.eval('F  S k=$O(^tfor("g1",k)) Q:k=""  S cnt=cnt+1')
test("FOR+$ORDER cuenta 3", enc.eval('$G(cnt)') == 3, f"got cnt={enc.eval('$G(cnt)')}")
test("FOR k final vacía", enc.eval('$G(k)') == "", f"got k={repr(enc.eval('$G(k)'))}")

print("\n=== TEST 7: FOR + $G dentro ===")
enc = fresh_enc()
enc.eval('S sum=0,k=""')
enc.eval('F  S k=$O(^tfor("g1",k)) Q:k=""  S val=$G(^tfor("g1",k)) S sum=sum+1')
test("FOR suma con $G", enc.eval('$G(sum)') == 3, f"got sum={enc.eval('$G(sum)')}")

print("\n=== TEST 8: $P con variable local ===")
enc = fresh_enc()
enc.scope.set('s', 'x#y#z')
r = enc.eval('$P($G(s),"#",2)')
test("$P($G(var),...)", r == 'y', f"got {repr(r)}")
enc.scope.set('s', '1^2^3')
r2 = enc.eval('$P($G(s),"^",3)')
test("$P con ^ delimiter", r2 == '3', f"got {repr(r2)}")

print("\n=== TEST 9: FOR anidado (producto cartesiano) ===")
enc = fresh_enc()
enc.eval('S n=0,i=""')
enc.eval('F  S i=$O(^tfor("g1",i)) Q:i=""  S j="" F  S j=$O(^tfor("g1",j)) Q:j=""  S n=n+1')
test("FOR anidado 3x3=9", enc.eval('$G(n)') == 9, f"got n={enc.eval('$G(n)')}")

print("\n=== TEST 10: FOR anidado simple (sin $O) ===")
enc = fresh_enc()
enc.eval('S n=0,i=0')
enc.eval('F  S i=i+1 Q:i>3  S j=0 F  S j=j+1 Q:j>3  S n=n+1')
test("FOR simple anidado 3x3=9", enc.eval('$G(n)') == 9, f"got n={enc.eval('$G(n)')}")

print("\n=== TEST 11: Datos reales (EXP) ===")
enc = fresh_enc()
enc.eval('S n=0,k=""')
enc.eval('F  S k=$O(^EXP("EXP01",k)) Q:k=""  S n=n+1')
test("EXP 178 pacientes", enc.eval('$G(n)') == 178, f"got n={enc.eval('$G(n)')}")

enc = fresh_enc()
enc.eval('S n=0,k=""')
enc.eval('F  S k=$O(^URG("URG01",k)) Q:k=""  S n=n+1')
test("URG 95 urgencias", enc.eval('$G(n)') == 95, f"got n={enc.eval('$G(n)')}")

# ── Cleanup ──
pdb_tools.tool_kill({"ns": "test", "subs": [1]})
pdb_tools.tool_kill({"ns": "tfor", "subs": [1]})

print(f"\n{'='*40}")
print(f"RESULTADOS: {PASS} passed, {FAIL} failed de {PASS+FAIL}")
print(f"{'✅ TODOS OK' if FAIL == 0 else f'❌ {FAIL} FALLOS'}")
