"""RAG Benchmark — 10 queries piloto"""
import os, sys, time
import pathlib
BASE = pathlib.Path('C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb')
sys.path.insert(0, str(BASE))
os.chdir(str(BASE))

import importlib
spec = importlib.util.spec_from_file_location('pdb_tools', str(BASE/'pdb_tools.py'))
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)

QUERIES = [
    ("urgencias veterinarias 24h Madrid", "urgencias"),
    ("clinica para gatos en Barcelona", "gatos"),
    ("veterinario economico en Sevilla", "sevilla"),
    ("veterinario especialista en reptiles", "reptiles"),
    ("peluqueria canina en Navarra", "estetica"),
    ("veterinario en Bilbao", "bilbao"),
    ("clinica para perros en Valencia", "valencia"),
    ("veterinario de guardia en Alicante", "urgencias|guardia"),
    ("centro de rehabilitacion para mascotas", "rehabilitacion"),
    ("tienda de animales en Madrid", "petshop"),
]

hits_at_1 = 0
hits_at_5 = 0
times = []

print(f"=== RAG Benchmark: {len(QUERIES)} queries ===")
print()

for i, (query, expected) in enumerate(QUERIES, 1):
    t0 = time.time()
    r = pdb_tools.tool_embed_search({'query': query, 'limit': 5})
    elapsed = time.time() - t0
    times.append(elapsed)
    
    top = r['results']
    top_texts = [t['text'] for t in top]
    
    # Check partial match on expected keyword
    hit1 = any(expected.lower() in t.lower() for t in top_texts[:1])
    hit5 = any(expected.lower() in t.lower() for t in top_texts[:5])
    if hit1: hits_at_1 += 1
    if hit5: hits_at_5 += 1
    
    icon = "✅" if hit5 else "⚠️" if hit1 else "❌"
    first = top[0]['text'][:70] if top else "(none)"
    score = top[0]['score'] if top else 0
    print(f"  {i:2d}. {icon} [{elapsed:5.1f}s] {query}")
    print(f"       → {first} ({score:.3f})")

avg_t = sum(times)/len(times)
print()
print(f"=== RESULTADOS ===")
print(f"  Precision@1: {hits_at_1}/{len(QUERIES)} = {hits_at_1/len(QUERIES)*100:.0f}%")
print(f"  Precision@5: {hits_at_5}/{len(QUERIES)} = {hits_at_5/len(QUERIES)*100:.0f}%")
print(f"  Tiempo medio: {avg_t:.1f}s")
print(f"  Tiempo total: {sum(times):.0f}s")
