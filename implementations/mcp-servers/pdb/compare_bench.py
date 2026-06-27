"""
LUMEN Benchmark Suite — Multi-model comparison
===============================================
Run this script in ANY Hermes session to benchmark LUMEN performance.
Results are stored in PDB under ^BENCH(model, run, metric).

Usage:
  python compare_bench.py ds-v4pro-max   # First model
  python compare_bench nous-free          # Second model (in other session)

Then compare:
  python compare_bench.py --report       # Shows both models side by side
"""
import os, sys, time, json, tempfile

MODEL = sys.argv[1] if len(sys.argv) > 1 else "unknown"
RUN = 1

os.environ['PDB_PATH'] = os.path.join(tempfile.mkdtemp(), f'bench_{MODEL}.db')
sys.path.insert(0, '.')
import pdb_tools
from m_light import MEvaluator

m = MEvaluator(pdb_tools)
results = {}

def metric(name, value, unit=''):
    results[name] = f'{value}{unit}'
    print(f'  {name}: {value}{unit}')

print(f'=== LUMEN Benchmark — {MODEL} #{RUN} ===')
print()

# 1. Raw PDB ops
print('1. Raw PDB')
t0 = time.perf_counter()
for i in range(100):
    pdb_tools.tool_set({'ns':'B','subs':[i],'value':str(i)})
ms = (time.perf_counter()-t0)*1000
metric('SET/s', round(100/(ms/1000)))
metric('SET_ms', round(ms/100, 2))

t0 = time.perf_counter()
for i in range(100):
    pdb_tools.tool_get({'ns':'B','subs':[i]})
ms = (time.perf_counter()-t0)*1000
metric('GET/s', round(100/(ms/1000)))
metric('GET_ms', round(ms/100, 3))

t0 = time.perf_counter()
pdb_tools.tool_order({'ns':'B','subs':['']})
ms = (time.perf_counter()-t0)*1000
metric('ORDER_all_ms', round(ms, 1))

# 2. M-Light
print('2. M-Light')
t0 = time.perf_counter()
for i in range(50):
    m.eval(f'S ^M({i})={i}')
ms = (time.perf_counter()-t0)*1000
metric('M_SET/s', round(50/(ms/1000)))

t0 = time.perf_counter()
for i in range(50):
    m.eval_expr(f'$G(^M({i}))')
ms = (time.perf_counter()-t0)*1000
metric('M_GET/s', round(50/(ms/1000)))

# 3. M expressions
print('3. M-Light Expressions')
exprs = ['$L("hello")', '$P("a|b|c","|",2)', '$TR("abc","abc","XYZ")', '$C(65)', '$SELECT(1=2:"no",1:"si")']
t0 = time.perf_counter()
for _ in range(10):
    for e in exprs:
        m.eval_expr(e)
ms = (time.perf_counter()-t0)*1000
metric('M_EXPR/s', round(50/(ms/1000)))

# 4. Enterprise
print('4. Enterprise')
t0 = time.perf_counter()
pdb_tools.tool_lock({'ns':'BE','timeout':5})
pdb_tools.tool_index_define({'ns':'BE','idx_name':'I1','sub_pos':1})
pdb_tools.tool_trigger_define({'ns':'BE','event':'ON_SET','action':'LOG','trigger_id':'t1'})
pdb_tools.tool_trigger_drop({'ns':'BE','trigger_id':'t1'})
pdb_tools.tool_index_drop({'ns':'BE','idx_name':'I1'})
pdb_tools.tool_unlock({'ns':'BE'})
ms = (time.perf_counter()-t0)*1000
metric('Enterprise_6ops_ms', round(ms, 1))

# 5. F loop
print('5. F loop $ORDER')
t0 = time.perf_counter()
m2 = MEvaluator(pdb_tools)
m2.eval('S I="" F  S I=$O(^B(I)) Q:I=""  S V=$G(^B(I))')
ms = (time.perf_counter()-t0)*1000
metric('F_loop_100_ms', round(ms, 1))

# Save
m.eval(f'S ^BENCH("{MODEL}","total")="{len(results)}"')
for i, (k, v) in enumerate(sorted(results.items()), 1):
    m.eval(f'S ^BENCH("{MODEL}","m",{i},"k")="{k}"')
    m.eval(f'S ^BENCH("{MODEL}","m",{i},"v")="{v}"')

print(f'\nSaved {len(results)} metrics in ^BENCH("{MODEL}")')
print('Run with second model, then compare.')
