#!/usr/bin/env python3
"""PDBM-Lumen: Mega PoC — importa travelmap + fishmap + farmamap."""
import os, sys, json, time, glob

DB = "C:\\temp\\pdb_ultra_poc.db"
os.environ["PDB_PATH"] = DB
os.makedirs("C:\\temp", exist_ok=True)
sys.path.insert(0, ".")
import pdb_tools as PDB

BASE = "C:\\Users\\gonzalo\\Documents\\GitHub\\ProjectOS"

# All data files organized by dataset
DATASETS = {
    "TRAVEL": [
        ("cultural",     "seed-travelmap-cultural.json",                True),
        ("cultural_ext", "seed-travelmap-mega-cultural_ext.json",       True),
        ("ruta_montana", "seed-travelmap-ruta_montana.json",            True),
        ("ruta_montana_ext","seed-travelmap-mega-ruta_montana_ext.json",True),
        ("ciclista",     "seed-travelmap-mega-ciclista.json",           True),
        ("camino",       "seed-travelmap-mega-camino.json",             True),
        ("acuatica",     "seed-travelmap-mega-acuatica.json",           True),
        ("via_ferrata",  "seed-travelmap-via_ferrata.json",             True),
        ("via_ferrata_ext","seed-travelmap-mega-via_ferrata_ext.json",  True),
    ],
    "FISHMAP": [
        ("spot",         "seed-fishmap-spots.json",                     False),  # dict {spots: [...], ...}
        ("beach",        "seed-fishmap-beaches-andalucia.json",          True),
        ("beach",        "seed-fishmap-beaches-baleares.json",           True),
        ("beach",        "seed-fishmap-beaches-canarias.json",           True),
        ("beach",        "seed-fishmap-beaches-cantabrico.json",         True),
        ("beach",        "seed-fishmap-beaches-cataluna.json",           True),
        ("beach",        "seed-fishmap-beaches-galicia.json",            True),
        ("beach",        "seed-fishmap-beaches-murcia.json",             True),
        ("beach",        "seed-fishmap-beaches-valencia.json",           True),
        ("apnea",        "seed-fishmap-apnea.json",                     False),  # dict {spots: [...]}
        ("embarcacion",  "seed-fishmap-embarcacion.json",                True),
        ("kayak",        "seed-fishmap-kayak.json",                      True),
        ("marisqueo",    "seed-fishmap-marisqueo.json",                  True),
        ("marisqueo_roca","seed-fishmap-marisqueo_roca.json",            True),
        ("nocturna",     "seed-fishmap-nocturna.json",                   True),
    ],
}

print("=" * 68)
print("  PDBM-Lumen: ULTRA PoC — Todos los datos")
print("=" * 68)

total_records = 0
total_time = 0.0
stats = {}

def extract_value(item, keys, default=""):
    for k in keys:
        v = item.get(k)
        if v: return v
    return default

def import_list(ns, tipo, items, prov_key, id_key, name_key):
    global total_records, total_time
    n = 0
    t0 = time.perf_counter()
    for item in items:
        if not isinstance(item, dict): continue
        prov = extract_value(item, prov_key, "Unknown")
        pid = str(item.get(id_key, hash(str(item))))
        name = item.get(name_key, "")
        PDB.tool_set({"ns": ns, "subs": [tipo, prov, pid], "value": {
            "name": name,
            "type": item.get("type", tipo),
            "subtype": item.get("subtype", ""),
            "lat": item.get("lat"),
            "lng": item.get("lng"),
            "difficulty": item.get("difficulty", ""),
            "duration_hours": item.get("duration_hours") or item.get("duration_min", 0) / 60 if item.get("duration_min") else None,
            "rating_avg": item.get("rating_avg") or item.get("rating", 0),
        }})
        n += 1
    t1 = time.perf_counter()
    elapsed = t1 - t0
    total_records += n
    total_time += elapsed
    stats[f"{ns}/{tipo}"] = n
    return n, elapsed

for ns, entries in DATASETS.items():
    print(f"\n📂 {ns}:")
    for tipo, filename, is_list in entries:
        filepath = os.path.join(BASE, filename)
        if not os.path.exists(filepath):
            print(f"  ⚠ {filename}: not found")
            continue
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if is_list:
            if not isinstance(data, list):
                data = [data]
            items = data
        else:
            if isinstance(data, dict):
                # Try common key patterns
                items = data.get("spots") or data.get("items") or data.get("data") or []
                if not items:
                    # Maybe it's a dict of dicts
                    flat = []
                    for k, v in data.items():
                        if isinstance(v, list):
                            flat.extend(v)
                        elif isinstance(v, dict):
                            v["_key"] = k
                            flat.append(v)
                    items = flat
            else:
                items = []
        
        # Different files have different key patterns
        if tipo == "spot":
            prov_key = ["provincia", "ccaa", "province"]
            id_key = "id"
            name_key = "name"
        elif tipo == "beach":
            prov_key = ["_zone", "municipio", "province"]
            id_key = "name"
            name_key = "name"
        elif tipo == "apnea":
            prov_key = ["provincia", "ccaa", "zone", "province"]
            id_key = "id"
            name_key = "name"
        else:
            prov_key = ["province", "ccaa", "municipio", "provincia", "zone"]
            id_key = "id"
            name_key = "name"
        
        n, elapsed = import_list(ns, tipo, items, prov_key, id_key, name_key)
        rate = n / elapsed if elapsed > 0 else 0
        print(f"  ✅ {tipo:20s} {n:>5} records  {elapsed*1000:>7.1f}ms  {rate:>7.0f} rec/s")

# Summary
avg_speed = total_records / total_time if total_time > 0 else 0
print("\n" + "=" * 68)
print(f"  TOTAL: {total_records:>5} records in {total_time*1000:.0f}ms ({avg_speed:.0f} rec/s)")
db_size = os.path.getsize(DB) if os.path.exists(DB) else 0
print(f"  DB: {db_size:,} bytes ({db_size/1024:.0f} KB)")
print()

# Per-type summary via $ORDER
print("📊 Per-type summary (\$ORDER):")
for ns in ["TRAVEL", "FISHMAP"]:
    print(f"\n  {ns}:")
    tipo = None
    while True:
        r = PDB.tool_order({"ns": ns, "subs": [tipo or ""], "direction": 1})
        if r["value"] is None: break
        tipo = r["value"]
        # Count items - use SQL if available, else full walk
        # Quick count with $ORDER at level 2
        c = 0
        prov = None
        while True:
            r2 = PDB.tool_order({"ns": ns, "subs": [tipo, prov or ""], "direction": 1})
            if r2["value"] is None: break
            prov = r2["value"]
            pid = None
            while True:
                r3 = PDB.tool_order({"ns": ns, "subs": [tipo, prov, pid or ""], "direction": 1})
                if r3["value"] is None: break
                pid = r3["value"]; c += 1
        print(f"    {tipo:20s} {c:>5} items")
        if tipo in stats:
            del stats[tipo]  # already counted

print(f"\n✅ PoC ultra completo! {total_records} records, {db_size:,} bytes")
