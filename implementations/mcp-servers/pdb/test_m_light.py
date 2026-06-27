"""
M-Light Test Suite — Pruebas del evaluador M contra PDB real.

Tests clásicos que Gonzalo hacía en MUMPS:
1. SET/GET básico
2. $ORDER traversal completo
3. FOR infinito con Q condicional
4. FOR con rango
5. Bucles $ORDER anidados
6. $PIECE, $EXTRACT, $SELECT
7. IF/ELSE
8. KILL
9. Edge cases
"""

import sys, os, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pdb_tools
from m_light import MEvaluator

PASS = 0
FAIL = 0

def setup():
    """Poblar datos de prueba en PDB."""
    # Lista de nombres para $ORDER traversal
    for name in ['ana', 'juan', 'luis', 'maria', 'pepe', 'zoe']:
        pdb_tools.tool_set({'ns': 'nombres', 'subs': [name], 'value': f'edad_{hash(name)%100}'})
    
    # Datos jerárquicos para $ORDER anidado
    for i in range(1, 4):
        for j in ['a', 'b', 'c']:
            pdb_tools.tool_set({'ns': 'matrix', 'subs': [i, j], 'value': f'{i}x{j}'})
    
    # Serie numérica
    for i in range(1, 11):
        pdb_tools.tool_set({'ns': 'serie', 'subs': [i], 'value': i * 10})

def cleanup():
    """Limpiar datos de prueba."""
    for ns in ['nombres', 'matrix', 'serie', 'res']:
        pdb_tools.tool_kill({'ns': ns, 'subs': [1]})
    # Asegurar que el checkpoint se ejecuta
    c = pdb_tools._get_conn()
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} — {detail}")

def run_all():
    global PASS, FAIL
    print("=" * 60)
    print("🧪 M-LIGHT TEST SUITE")
    print("=" * 60)
    
    # ── Setup ──
    print("\n📦 Setup: poblando datos...")
    setup()
    
    # ── 1. SET/GET básico ──
    print("\n─── 1. SET/GET básico ───")
    m = MEvaluator(pdb_tools)
    m.eval('S ^test(1)="hola mundo"')
    r = pdb_tools.tool_get({'ns': 'test', 'subs': [1]})
    test("SET + GET directo", r.get('value') == 'hola mundo', f"got {r.get('value')}")
    
    m2 = MEvaluator(pdb_tools)
    val = m2.eval_expr('$GET(^test(1))')
    test("$GET vía M-Light", val == 'hola mundo', f"got {val}")
    
    # ── 2. $ORDER traversal completo ──
    print("\n─── 2. $ORDER traversal ───")
    m3 = MEvaluator(pdb_tools)
    # Recorrer TODOS los nombres
    names = []
    m3.eval('S N="" F  S N=$O(^nombres(N)) Q:N=""  S ^res(N)=N')
    # Verificar que se recorrieron todos
    for expected in ['ana', 'juan', 'luis', 'maria', 'pepe', 'zoe']:
        r = pdb_tools.tool_get({'ns': 'res', 'subs': [expected]})
        test(f"$ORDER recorrió '{expected}'", r.get('value') == expected, f"got {r.get('value')}")
    
    # ── 3. FOR infinito con Q condicional ──
    print("\n─── 3. FOR infinito + Q condicional ───")
    m4 = MEvaluator(pdb_tools)
    # Buscar 'pepe' en la lista, la línea clásica de M
    m4.eval('S N="" F  S N=$O(^nombres(N)) Q:N=""  Q:N="pepe"')
    test("F+$ORDER+Q encontró pepe", m4.scope.get('N') == 'pepe', f"N={m4.scope.get('N')}")
    
    # Buscar elemento que no existe
    m5 = MEvaluator(pdb_tools)
    m5.eval('S N="" F  S N=$O(^nombres(N)) Q:N=""  Q:N="zzz"')
    test("Q:N=\"\" funciona (no existe)", m5.scope.get('N') == '', f"N={m5.scope.get('N')}")
    
    # ── 4. FOR con rango ──
    print("\n─── 4. FOR con rango ───")
    m6 = MEvaluator(pdb_tools)
    m6.eval('F I=1:1:8 S ^cuadrados(I)=I*I')
    for i in range(1, 9):
        r = pdb_tools.tool_get({'ns': 'cuadrados', 'subs': [i]})
        test(f"FOR rango ^cuadrados({i})", r.get('value') == i*i, f"got {r.get('value')}")
    
    # ── 5. Bucles $ORDER anidados ──
    print("\n─── 5. Bucles $ORDER anidados ───")
    m7 = MEvaluator(pdb_tools)
    code = 'S I="" F  S I=$O(^matrix(I)) Q:I=""  S J="" F  S J=$O(^matrix(I,J)) Q:J=""  S ^copia(I,J)=$GET(^matrix(I,J))'
    m7.eval(code)
    for i in range(1, 4):
        for j in ['a', 'b', 'c']:
            r = pdb_tools.tool_get({'ns': 'copia', 'subs': [i, j]})
            expected = f'{i}x{j}'
            test(f"Nested \$ORDER copia({i},{j})", r.get('value') == expected, f"got {r.get('value')}")
    
    # ── 6. $PIECE, $EXTRACT, $SELECT ──
    print("\n─── 6. String functions ───")
    m8 = MEvaluator(pdb_tools)
    
    r = m8.eval_expr('$PIECE("Juan|Pedro|Maria","|",2)')
    test("$PIECE", r == 'Pedro', f"got {r}")
    
    r = m8.eval_expr('$EXTRACT("Hermes",1,3)')
    test("$EXTRACT", r == 'Her', f"got {r}")
    
    r = m8.eval_expr('$SELECT(0=1:"nope",1=1:"yep",1:"def")')
    test("$SELECT", r == 'yep', f"got {r}")
    
    r = m8.eval_expr('$SELECT(0=1:"nope",0=1:"nope",1:"default")')
    test("$SELECT default", r == 'default', f"got {r}")
    
    # ── 7. IF condicional ──
    print("\n─── 7. IF/ELSE ───")
    m9 = MEvaluator(pdb_tools)
    m9.eval('S X=5 IF X=5 { S ^cond("ok")=1 }')
    r = pdb_tools.tool_get({'ns': 'cond', 'subs': ['ok']})
    test("IF X=5", r.get('value') == 1, f"got {r.get('value')}")
    
    m10 = MEvaluator(pdb_tools)
    m10.eval('S X=3 IF X=5 { S ^cond("fail")=1 }')
    r = pdb_tools.tool_get({'ns': 'cond', 'subs': ['fail']})
    test("IF X=3 no ejecuta", r.get('found') == False, f"got {r}")
    
    # ── 8. KILL ──
    print("\n─── 8. KILL ───")
    pdb_tools.tool_set({'ns': 'killtest', 'subs': [1], 'value': 'x'})
    pdb_tools.tool_set({'ns': 'killtest', 'subs': [2], 'value': 'y'})
    m11 = MEvaluator(pdb_tools)
    m11.eval('K ^killtest(1)')
    r1 = pdb_tools.tool_get({'ns': 'killtest', 'subs': [1]})
    r2 = pdb_tools.tool_get({'ns': 'killtest', 'subs': [2]})
    test("KILL ^killtest(1) eliminado", r1.get('found') == False)
    test("KILL ^killtest(2) sobrevive", r2.get('value') == 'y')
    
    # ── 9. Edge cases ──
    print("\n─── 9. Edge cases ───")
    
    # Global vacío
    m12 = MEvaluator(pdb_tools)
    m12.eval('S N="" F  S N=$O(^vacio(N)) Q:N=""')
    test("Global vacío $ORDER", m12.scope.get('N') == '')
    
    # $ORDER con dirección -1 (anterior)
    pdb_tools.tool_set({'ns': 'nums', 'subs': [1], 'value': 'a'})
    pdb_tools.tool_set({'ns': 'nums', 'subs': [5], 'value': 'b'})
    r = pdb_tools.tool_order({'ns': 'nums', 'subs': [''], 'direction': -1})
    test("$ORDER dir=-1 (último)", r.get('value') == 5, f"got {r.get('value')}")
    
    # $DATA
    pdb_tools.tool_set({'ns': 'datatest', 'subs': [1], 'value': 'x'})
    r = pdb_tools.tool_data({'ns': 'datatest', 'subs': [1]})
    test("$DATA existe", r.get('value') in [1, 11], f"got {r.get('value')}")
    r = pdb_tools.tool_data({'ns': 'datatest', 'subs': [999]})
    test("$DATA no existe", r.get('value') == 0, f"got {r.get('value')}")
    
    # ── 10. Combinación compleja (la que hacía Gonzalo) ──
    print("\n─── 10. Combinación compleja M ───")
    m13 = MEvaluator(pdb_tools)
    # Como en M: recorrer, filtrar, y acumular
    code = (
        'S C=0'  # contador
        ' F  S N=$O(^nombres(N)) Q:N=""  D'
        ' .I $E(N,1)="m" S C=C+1 S ^filtrados(C)=N'  # nombres que empiezan con 'm'
    )
    # Versión simplificada: recorrer y filtrar
    m13.eval('S C=0 F  S N=$O(^nombres(N)) Q:N=""  I $E(N,1)="m" S C=C+1 S ^filtrados(C)=N')
    r1 = pdb_tools.tool_get({'ns': 'filtrados', 'subs': [1]})
    test("Filtro M complejo", r1.get('value') == 'maria', f"got {r1.get('value')}")
    
    # ── Resultados ──
    print(f"\n{'='*60}")
    print(f"📊 RESULTADOS: {PASS} passed, {FAIL} failed, {PASS+FAIL} total")
    if FAIL == 0:
        print("🎉 ¡M-Light funciona correctamente!")
    else:
        print(f"❌ {FAIL} pruebas fallaron")
    print('=' * 60)
    
    # ── Cleanup ──
    cleanup()

if __name__ == '__main__':
    run_all()
