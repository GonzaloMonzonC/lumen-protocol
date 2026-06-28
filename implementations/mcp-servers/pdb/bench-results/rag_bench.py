"""RAG Benchmark — 60 queries sobre 1729 veterinarias en PDB"""
import os, sys, time, math, json
import pathlib

BASE = pathlib.Path('C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb')
sys.path.insert(0, str(BASE))
os.chdir(str(BASE))

import importlib
spec = importlib.util.spec_from_file_location('pdb_tools', 'pdb_tools.py')
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)

QUERIES = [
    # Urgencias / emergencias
    ("urgencias veterinarias 24h Madrid", "urgencias"),
    ("veterinario de guardia en Barcelona", "urgencias|guardia"),
    ("emergencias con perros en Valencia", "urgencias|emergencia"),
    ("veterinario nocturno en Sevilla", "urgencias|nocturno"),
    ("clinica de urgencias para gatos", "urgencias"),
    # Por provincia
    ("veterinario en Madrid capital", "madrid"),
    ("clinica veterinaria en Barcelona", "barcelona"),
    ("veterinario en Valencia", "valencia"),
    ("clinica para perros en Sevilla", "sevilla"),
    ("veterinario en Bilbao", "bilbao"),
    ("clinica veterinaria en Zaragoza", "zaragoza"),
    ("veterinario en Málaga", "malaga"),
    ("clinica para mascotas en Murcia", "murcia"),
    ("veterinario en Palma de Mallorca", "palma"),
    ("clinica veterinaria en Alicante", "alicante"),
    ("veterinario en Córdoba", "cordoba"),
    ("clinica en Valladolid", "valladolid"),
    ("veterinario en Vigo", "vigo"),
    ("clinica en Gijón", "gijon"),
    ("veterinario en Granada", "granada"),
    # Por especie
    ("veterinario especialista en gatos", "gatos"),
    ("clinica para perros grandes", "perros"),
    ("veterinario que atienda conejos", "conejos"),
    ("clinica para aves y exoticos", "aves|exotico"),
    ("veterinario para reptiles", "reptiles"),
    ("consulta para hurones", "hurones"),
    ("veterinario para animales exoticos", "exotico"),
    ("clinica que atienda roedores", "roedores|hamster"),
    ("veterinario para caballos", "caballos"),
    ("clinica para gatos y perros juntos", "gatos.*perros|perros.*gatos"),
    # Por tipo de servicio
    ("peluqueria canina en Madrid", "estetica|peluqueria"),
    ("tienda de animales en Barcelona", "petshop|tienda"),
    ("centro de estetica para perros", "estetica"),
    ("veterinario con servicio a domicilio", "domicilio"),
    ("clinica con radiografia y ecografia", "radiografia|ecografia"),
    ("veterinario que haga analisis clinicos", "analisis|laboratorio"),
    ("hospital veterinario 24 horas", "hospital"),
    ("centro de rehabilitacion para perros", "rehabilitacion|fisioterapia"),
    ("veterinario con quirofano", "quirofano|cirugia"),
    ("consulta de etologia canina", "etologia|comportamiento"),
    # Por zona geográfica (norte)
    ("veterinario en Galicia", "galicia"),
    ("clinica en Asturias", "asturias"),
    ("veterinario en Cantabria", "cantabria"),
    ("clinica en Pais Vasco", "pais vasco"),
    ("veterinario en Navarra", "navarra"),
    # Por zona geográfica (sur)
    ("veterinario en Andalucia", "andalucia"),
    ("clinica en Extremadura", "extremadura"),
    ("veterinario en Canarias", "canarias"),
    # Por zona geográfica (este)
    ("veterinario en Cataluña", "cataluña"),
    ("clinica en Comunidad Valenciana", "valencia"),
    ("veterinario en Baleares", "baleares"),
    # Varios
    ("clinica veterinaria cerca de mi", "veterinaria"),
    ("mejor veterinario de la zona", "veterinario"),
    ("veterinario barato y bueno", "veterinaria"),
    ("donde llevar a mi perro enfermo", "veterinaria"),
    ("clinica para mascotas pequenas", "veterinaria"),
    ("veterinario de confianza en mi barrio", "veterinario"),
    ("centro veterinario con buen precio", "veterinaria"),
    ("veterinario para gato en adopcion", "gatos"),
    ("clinica canina con buena reputacion", "veterinaria"),
    ("donde vacunar a mi perro", "veterinaria"),
]

results = []
times = []
total_hits_at_1 = 0
total_hits_at_5 = 0

print(f"=== RAG Benchmark: {len(QUERIES)} queries sobre {len(pdb_tools.tool_embed_search({'query': 'test', 'limit': 1})['results'])} indices ===")
print()

for i, (query, expected) in enumerate(QUERIES, 1):
    t0 = time.time()
    r = pdb_tools.tool_embed_search({'query': query, 'limit': 5})
    elapsed = time.time() - t0
    
    top_texts = [res['text'] for res in r['results']]
    top_scores = [res['score'] for res in r['results']]
    
    # Check relevance: does any top result contain expected keyword?
    hit_at_1 = any(expected.lower() in t.lower() for t in top_texts[:1])
    hit_at_5 = any(expected.lower() in t.lower() for t in top_texts[:5])
    
    results.append((query, expected, top_texts[0] if top_texts else '', top_scores[0] if top_scores else 0, hit_at_1, hit_at_5, elapsed))
    times.append(elapsed)
    if hit_at_1: total_hits_at_1 += 1
    if hit_at_5: total_hits_at_5 += 1
    
    status = "✅" if hit_at_5 else "❌"
    print(f"  {i:2d}. [{status}] [{elapsed:5.1f}s] {query}")
    print(f"       → {top_texts[0][:70] if top_texts else '(none)'} ({top_scores[0]:.3f})")

# Summary
avg_time = sum(times) / len(times)
print()
print("=" * 60)
print(f"RESUMEN: {len(QUERIES)} queries sobre {len(top_texts)} embeddings")
print(f"  Precision@1: {total_hits_at_1}/{len(QUERIES)} = {total_hits_at_1/len(QUERIES)*100:.1f}%")
print(f"  Precision@5: {total_hits_at_5}/{len(QUERIES)} = {total_hits_at_5/len(QUERIES)*100:.1f}%")
print(f"  Tiempo medio: {avg_time:.1f}s")
print(f"  Tiempo total: {sum(times):.0f}s")
