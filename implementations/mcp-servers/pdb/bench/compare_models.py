import os, sys
sys.path.insert(0, '.')

models = ['ds-v4pro-max', 'nous-free', 'LagunaM1', 'nemotron-3-super-120b-a12b-free', 'nemotron-ultra-free']
data = {}

for model in models:
    db_path = os.path.join('bench_cache', f'bench_{model}.db')
    if not os.path.exists(db_path):
        print(f'Missing: {db_path}')
        continue
    os.environ['PDB_PATH'] = db_path
    import pdb_tools
    import importlib
    importlib.reload(pdb_tools)

    metrics = {}
    total = int(pdb_tools.tool_get({'ns':'BENCH','subs':[model,'total']})['value'] or 0)
    for i in range(1, total+1):
        k = pdb_tools.tool_get({'ns':'BENCH','subs':[model,'m',i,'k']})['value']
        v = pdb_tools.tool_get({'ns':'BENCH','subs':[model,'m',i,'v']})['value']
        metrics[k] = v
    data[model] = metrics

print('=== Benchmark Comparison (4 models) ===')
print()

# Build header
header = f"{'Metric':25s}"
for m in models:
    header += f" {m:18s}"
print(header)
print('-' * (25 + 22*len(models)))

for k in sorted(data[models[0]].keys()):
    row = f'{k:25s}'
    vals = []
    for m in models:
        v = data[m].get(k, '-')
        vals.append(v)
        row += f" {v:18s}"

    # Compute diffs vs first model (ds-v4pro-max)
    diffs = []
    for i, v in enumerate(vals[1:], 1):
        try:
            n0 = float(vals[0])
            ni = float(v)
            diff = ((ni - n0) / n0) * 100 if n0 else 0
            diffs.append(f'{diff:+.1f}%')
        except:
            diffs.append('')
    if any(diffs):
        row += f" {' vs '.join(diffs)}"
    print(row)
