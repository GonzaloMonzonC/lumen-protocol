"""RAG Benchmark — 60 queries (optimizado numpy + cache)"""
import os, sys, time
sys.path.insert(0, 'C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb')
os.chdir('C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb')

import importlib
spec = importlib.util.spec_from_file_location('pdb_tools', 'pdb_tools.py')
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)

QUERIES = [
    # Urgencias
    ("urgencias veterinarias 24h Madrid", "urgencias|madrid"),
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
    ("veterinario en Malaga", "malaga"),
    ("clinica para mascotas en Murcia", "murcia"),
    ("veterinario en Palma de Mallorca", "palma"),
    ("clinica veterinaria en Alicante", "alicante"),
    ("veterinario en Cordoba", "cordoba"),
    ("clinica en Valladolid", "valladolid"),
    ("veterinario en Vigo", "vigo"),
    ("clinica en Gijon", "gijon"),
    ("veterinario en Granada", "granada"),
    # Por especie
    ("veterinario especialista en gatos", "gatos"),
    ("clinica para perros grandes", "perros"),
    ("veterinario que atienda conejos", "conejos"),
    ("clinica para aves exoticas", "aves"),
    ("veterinario para reptiles", "reptiles"),
    ("consulta para hurones", "hurones"),
    ("veterinario para animales exoticos", "exotico"),
    ("clinica que atienda roedores", "roedores"),
    ("veterinario para caballos", "caballos"),
    ("clinica para gatos y perros", "gatos"),
    # Por tipo de servicio
    ("peluqueria canina en Madrid", "estetica"),
    ("tienda de animales en Barcelona", "petshop"),
    ("centro de estetica para perros", "estetica"),
    ("veterinario con servicio a domicilio", "domicilio"),
    ("clinica con radiografia", "radiografia"),
    ("veterinario que haga analisis", "analisis"),
    ("hospital veterinario 24 horas", "hospital"),
    ("centro de rehabilitacion para mascotas", "rehabilitacion"),
    ("veterinario con quirofano", "quirofano"),
    ("consulta de etologia canina", "etologia"),
    # Por zona norte
    ("veterinario en Galicia", "galicia"),
    ("clinica en Asturias", "asturias"),
    ("veterinario en Cantabria", "cantabria"),
    ("clinica en Pais Vasco", "pais vasco"),
    ("veterinario en Navarra", "navarra"),
    # Por zona sur
    ("veterinario en Andalucia", "andalucia"),
    ("clinica en Extremadura", "extremadura"),
    ("veterinario en Canarias", "canarias"),
    # Por zona este
    ("veterinario en Cataluña", "cataluna|catalunya"),
    ("clinica en Comunidad Valenciana", "valencia"),
    ("veterinario en Baleares", "baleares"),
    # Varios
    ("clinica veterinaria cerca de mi", "veterinaria"),
    ("mejor veterinario de la zona", "veterinario"),
    ("veterinario barato y bueno", "veterinaria"),
    ("donde llevar a mi perro enfermo", "veterinaria"),
    ("clinica para mascotas pequeñas", "veterinaria"),
    ("veterinario de confianza en mi barrio", "veterinario"),
    ("centro veterinario con buen precio", "veterinaria"),
    ("veterinario para gato en adopcion", "gato"),
    ("clinica canina con buena reputacion", "veterinaria"),
    ("donde vacunar a mi perro", "veterinaria"),
]

hits_1 = 0
hits_5 = 0
times = []

print("=== RAG Benchmark: 60 queries ===")
print()

for i, (query, expected) in enumerate(QUERIES, 1):
    t0 = time.time()
    r = pdb_tools.tool_embed_search({'query': query, 'limit': 5})
    elapsed = time.time() - t0
    times.append(elapsed)
    
    texts = [res['text'] for res in r['results']]
    scores = [res['score'] for res in r['results']]
    
    hit1 = any(e.lower() in (texts[0] if texts else '').lower() for e in expected.split('|'))
    hit5 = any(any(e.lower() in t.lower() for e in expected.split('|')) for t in texts[:5])
    if hit1: hits_1 += 1
    if hit5: hits_5 += 1
    
    icon = "✅" if hit5 else "⚠️" if hit1 else "❌"
    first = texts[0][:60] if texts else "(none)"
    print(f"  {i:2d}. {icon} [{elapsed*1000:5.0f}ms] {query}")
    print(f"       -> {first} ({scores[0]:.3f})")

avg_t = sum(times)/len(times)
print()
print("=" * 60)
print(f"RESUMEN: {len(QUERIES)} queries")
print(f"  Precision@1: {hits_1}/{len(QUERIES)} = {hits_1/len(QUERIES)*100:.1f}%")
print(f"  Precision@5: {hits_5}/{len(QUERIES)} = {hits_5/len(QUERIES)*100:.1f}%")
print(f"  Tiempo medio: {avg_t*1000:.0f}ms")
print(f"  Tiempo total: {sum(times):.0f}s")
