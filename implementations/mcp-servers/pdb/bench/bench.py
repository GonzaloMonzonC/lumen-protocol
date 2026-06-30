"""
LUMEN Benchmark Suite — Multi-model comparison
===============================================
Mide el RENDIMIENTO BRUTO de PDB + M-Light desde Python.
NO mide la inteligencia del modelo — para eso, la otra sesion
debe usar las LUMEN tools directamente (sequential_thinking,
PDB ops via MCP, etc.) y nosotros comparamos patrones de uso.

USO:
  python bench.py ds-v4pro-max     # Guarda métricas en PDB real
  python bench.py nous-free         # Segundo modelo (otra sesion)
  python bench.py --report          # Compara side-by-side via $ORDER
"""
import os, sys, time

MODEL = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else None
MODE = sys.argv[1] if len(sys.argv) > 1 else 'run'

# Use MAIN PDB so results persist across sessions
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdb_tools
from m_light import MEvaluator

def show_report():
    """Compara todos los modelos guardados en ^BENCH"""
    print('=== LUMEN Multi-Model Comparison ===')
    print()
    models = []
    I = ''
    while True:
        r = pdb_tools.tool_order({'ns':'BENCH','subs':[I]})
        if not r.get('value'): break
        I = r['value']
        if I not in models: models.append(I)
    
    if not models:
        print('No hay datos. Ejecuta: python bench.py <modelo>')
        return
    
    metrics = set()
    model_data = {}
    for model in models:
        J = ''
        data = {}
        while True:
            r = pdb_tools.tool_order({'ns':'BENCH','subs':[model, J]})
            if not r.get('value'): break
            J = r['value']
            v = pdb_tools.tool_get({'ns':'BENCH','subs':[model, J]})
            data[J] = v.get('value', '?')
            metrics.add(J)
        model_data[model] = data
    
    # Print table
    header = f"{'Metric':>18s}"
    for model in models:
        header += f" | {model:>16s}"
    print(header)
    print('-' * (18 + 19 * len(models)))
    
    for metric in sorted(metrics):
        row = f"{metric:>18s}"
        for model in models:
            val = model_data[model].get(metric, '-')
            row += f" | {val:>16s}"
        print(row)

def run_bench(model):
    """Ejecuta el benchmark y guarda en ^BENCH(model)"""
    m = MEvaluator(pdb_tools)
    
    def save(k, v):
        pdb_tools.tool_set({'ns':'BENCH','subs':[model,k],'value':str(v)})
    
    print(f'=== LUMEN Benchmark: {model} ===')
    print('(Mide velocidad bruta PDB/M-Light, NO inteligencia del modelo)')
    print()
    
    # Clean previous run for this model
    try:
        pdb_tools.tool_kill({'ns':'BENCH','subs':[model]})
    except: pass
    
    # 1. Raw PDB
    print('1. Raw PDB ops')
    t0 = time.perf_counter()
    for i in range(100):
        pdb_tools.tool_set({'ns':'BENCH','subs':['_tmp',i],'value':str(i)})
    ms = (time.perf_counter()-t0)*1000
    save('SET_s', round(100/(ms/1000)))
    v1 = round(100/(ms/1000))
    print(f'  SET: {v1} /s')
    
    t0 = time.perf_counter()
    for i in range(100):
        pdb_tools.tool_get({'ns':'BENCH','subs':['_tmp',i]})
    ms = (time.perf_counter()-t0)*1000
    save('GET_s', round(100/(ms/1000)))
    print(f'  GET: {round(100/(ms/1000))} /s')
    
    # 2. M-Light
    print('2. M-Light')
    t0 = time.perf_counter()
    for i in range(50):
        m.eval(f'S ^BENCH(\"_mtmp\",{i})={i}')
    ms = (time.perf_counter()-t0)*1000
    save('M_SET_s', round(50/(ms/1000)))
    
    t0 = time.perf_counter()
    for i in range(50):
        m.eval_expr(f'\$G(^BENCH(\"_mtmp\",{i}))')
    ms = (time.perf_counter()-t0)*1000
    save('M_GET_s', round(50/(ms/1000)))
    
    t0 = time.perf_counter()
    for _ in range(10):
        for e in ['\$L(\"hello\")', '\$P(\"a|b|c\",\"|\",2)', '\$TR(\"abc\",\"abc\",\"XYZ\")', '\$C(65)']:
            m.eval_expr(e)
    ms = (time.perf_counter()-t0)*1000
    save('M_EXPR_s', round(40/(ms/1000)))
    print(f'  M_EXPR: {round(40/(ms/1000))} /s')
    
    # 3. F loop
    print('3. F loop traversal')
    t0 = time.perf_counter()
    m2 = MEvaluator(pdb_tools)
    m2.eval('S I=\"\" F  S I=\$O(^BENCH(\"_tmp\",I)) Q:I=\"\"  S V=\$G(^BENCH(\"_tmp\",I))')
    ms = (time.perf_counter()-t0)*1000
    save('F_LOOP_ms', round(ms,1))
    print(f'  100 items: {round(ms,1)} ms')
    
    # Clean temp
    pdb_tools.tool_kill({'ns':'BENCH','subs':['_tmp']})
    pdb_tools.tool_kill({'ns':'BENCH','subs':['_mtmp']})
    
    print(f'\n=== Guardado en ^BENCH(\"{model}\") ===')
    print(f'Compara: python bench.py --report')

if __name__ == '__main__':
    if MODE == '--report':
        show_report()
    elif MODEL:
        run_bench(MODEL)
    else:
        print('Uso: python bench.py <modelo>')
        print('     python bench.py --report')
