"""
LUMEN Cognitive Benchmark v2 — Judge (alpha)
=============================================
Analyzes PDB structures and validates model performance on 3 open circuits.

Usage:
    python judge_v2.py                  # Score all models
    python judge_v2.py --detail <model>  # Detailed breakdown
    python judge_v2.py --json            # JSON output
"""

import os, sys, json, re, math
from pathlib import Path
from collections import Counter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pdb_tools

CIRCUITS = [
    {"id": 1, "name": "Data Modeling",  "weight": 0.40},
    {"id": 2, "name": "Debugging",      "weight": 0.30},
    {"id": 3, "name": "Optimization",   "weight": 0.30},
]

# Ground truth for the clean seed (computed from seed_farmacias_madrid.json)
GROUND_TRUTH = {
    "total_count": 500,
    "avg_lat": 40.4257,  # exact average of 500 pharmacies
    "unique_cps": 1,    # all NULL
    "top_street": "CALLE",
}


# ── Helpers ────────────────────────────────────────────────────────────

def tg(ns, subs):
    """pdb_get safe."""
    try:
        r = pdb_tools.tool_get({"ns": ns, "subs": subs})
        return r.get("value")
    except:
        return None

def to(ns, subs):
    """pdb_order safe."""
    try:
        r = pdb_tools.tool_order({"ns": ns, "subs": subs})
        return r.get("value")
    except:
        return None

def td(ns, subs):
    """pdb_data safe - returns value key from tool_data."""
    try:
        r = pdb_tools.tool_data({"ns": ns, "subs": subs})
        # Debug
        v = r.get("value", 0)
        return v
    except:
        return 0

def k(ns, subs):
    """pdb_kill safe (cleanup)."""
    try:
        pdb_tools.tool_kill({"ns": ns, "subs": subs})
    except:
        pass

def walk_global(ns, max_depth=4):
    """Walk a ^GLOBAL structure and return its shape."""
    shape = {"depth": 0, "subscripts_by_level": {}, "leaf_count": 0, "field_names": set()}

    def _walk(subs, depth):
        if depth > max_depth:
            return
        if depth > shape["depth"]:
            shape["depth"] = depth
        I = ''
        while True:
            r = to(ns, subs + [I])
            if not r:
                break
            I = r
            # Check if this node has a value (leaf) or children
            data = td(ns, subs + [I])
            if data in (1, 11):  # has value
                shape["leaf_count"] += 1
                if depth >= 1:
                    shape["field_names"].add(str(I))
            if data in (10, 11):  # has children
                _walk(subs + [I], depth + 1)

    _walk([], 0)
    shape["field_count"] = len(shape["field_names"])
    return shape


def get_models():
    """Find models that ran v2."""
    models = []
    I = ''
    while True:
        r = to('BENCH_MODEL_V2', [I])
        if not r:
            break
        I = r
        if I and not I.startswith('_'):
            models.append(I)
    return models


def safe_float(v, default=0.0):
    if v is None:
        return default
    try:
        return float(v)
    except:
        return default


# ── Circuit 1: Data Modeling ──────────────────────────────────────────

def score_circuit_1(model):
    """Evaluate data model design. Analyze structure, count, naming."""
    criteria = {}
    details = []

    global_name = tg('BENCH_MODEL_V2', [model, 1, "global_name"])
    count = tg('BENCH_MODEL_V2', [model, 1, "count"])
    status = tg('BENCH_MODEL_V2', [model, 1, "status"])

    if status != "done" or not global_name:
        return {"score": 0.0, "criteria": {"c1_status": 0.0}, "details": ["Model did not complete C1"]}

    # c1a: Data loaded — check count matches
    c1a = 1.0 if safe_float(count) == GROUND_TRUTH["total_count"] else safe_float(count) / GROUND_TRUTH["total_count"] if safe_float(count) > 0 else 0.0
    criteria["c1a_count_correct"] = round(c1a, 4)
    details.append(f"  Records loaded: {count} (expected {GROUND_TRUTH['total_count']}) → {c1a:.2f}")

    # c1b: Structure analysis — walk the global the model created
    gns_raw = str(global_name).strip('\'" ')
    # Remove leading ^ if present (PDB namespaces don't use caret)
    gns = gns_raw.lstrip('^')
    shape = walk_global(gns)

    # Depth: should be at least 2 (id → field). Depth 1 = flat, 2 = id+field, 3+ = hierarchical
    ideal_depth = 2  # minimum: ^GLOBAL(id, field)
    c1b_depth = min(1.0, shape["depth"] / ideal_depth)
    details.append(f"  Structure depth: {shape['depth']} (ideal ≥{ideal_depth}) → {c1b_depth:.2f}")

    # Field coverage: how many of the 11 original fields exist
    expected_fields = {'id', 'nombre', 'direccion', 'cp', 'ciudad', 'municipio',
                       'provincia', 'comunidad', 'latitud', 'longitud', 'telefono'}
    found_fields = shape["field_names"]
    coverage = len(found_fields & expected_fields) / len(expected_fields)
    c1b_fields = round(coverage, 4)
    details.append(f"  Field coverage: {len(found_fields & expected_fields)}/{len(expected_fields)} → {c1b_fields:.2f}")
    if expected_fields - found_fields:
        details.append(f"  Missing fields: {expected_fields - found_fields}")

    c1b = (c1b_depth + c1b_fields) / 2.0
    criteria["c1b_structure_quality"] = round(c1b, 4)
    criteria["c1b_depth"] = c1b_depth
    criteria["c1b_fields"] = c1b_fields

    # c1c: Decision logged
    decision_data = td('DECISIONS', [''])
    c1c = 1.0 if decision_data and decision_data > 0 else 0.0
    # Fallback: check if model saved decision_logged key
    dl = tg('BENCH_MODEL_V2', [model, 1, "decision_logged"])
    if dl and str(dl).lower() in ('yes', '1', 'true'):
        c1c = 1.0
    criteria["c1c_decision_logged"] = c1c
    details.append(f"  Decision logged? → {c1c:.2f}")

    # c1d: Subscript structure described
    sub_structure = tg('BENCH_MODEL_V2', [model, 1, "subscript_structure"])
    c1d = 1.0 if sub_structure and len(str(sub_structure)) > 5 else 0.0
    criteria["c1d_subscript_documented"] = c1d
    details.append(f"  Subscript structure documented? → {c1d:.2f}")

    score = (c1a + c1b + c1c + c1d) / 4.0
    return {"score": round(score, 4), "criteria": criteria, "details": details}


# ── Circuit 2: Debugging ──────────────────────────────────────────────

# The 6 bug types planted
BUG_TYPES = {
    'lat_null': r'latitud.*(null|none|ausente|falt|missing|vacia)',
    'nombre_vacio': r'nombre.*(vacio|empty|blank|vacio|ausente|sin)',
    'ciudad_out': r'(ciudad|provincia).*(inconsist|incorrect|mismatch|fuera|barcelona|valencia)',
    'lat_string': r'latitud.*(string|texto|formato|invalid|cuarenta|text)',
    'telefono_null': r'telefono.*(null|none|ausente|falt|missing|sin)',
    'id_duplicado': r'(id|duplic|repet|duplicate|conflict|repetido)',
}


def score_circuit_2(model):
    """Validate debugging: how many of 6 planted bugs were found."""
    criteria = {}
    details = []

    status = tg('BENCH_MODEL_V2', [model, 2, "status"])
    if status != "done":
        return {"score": 0.0, "criteria": {"c2_status": 0.0}, "details": ["Model did not complete C2"]}

    bugs_found = tg('BENCH_MODEL_V2', [model, 2, "bugs_found"])
    bug_types_raw = tg('BENCH_MODEL_V2', [model, 2, "bug_types"])
    summary = tg('BENCH_MODEL_V2', [model, 2, "summary"])

    # c2a: Number of bugs found
    bf = safe_float(bugs_found) if bugs_found else 0
    c2a = min(1.0, bf / 12.0)  # ~14 bugs planted, 12 is passing
    criteria["c2a_bugs_detected"] = c2a
    details.append(f"  Bugs reported: {bf} → {c2a:.2f}")

    # c2b: Bug types identified (check summary for keywords)
    if summary:
        summary_lower = str(summary).lower()
        types_found = 0
        for bug_type, pattern in BUG_TYPES.items():
            if re.search(pattern, summary_lower):
                types_found += 1
        c2b = types_found / len(BUG_TYPES)
        details.append(f"  Bug types identified: {types_found}/{len(BUG_TYPES)} → {c2b:.2f}")
    else:
        c2b = 0.0
        details.append(f"  No summary provided → 0.0")
    criteria["c2b_bug_types_identified"] = c2b

    # c2c: Decision logged about debugging approach
    decision_data = td('DECISIONS', [''])
    c2c = 1.0 if decision_data and decision_data > 0 else 0.0
    dl = tg('BENCH_MODEL_V2', [model, 2, "decision_logged"])
    if dl and str(dl).lower() in ('yes', '1', 'true'):
        c2c = 1.0
    criteria["c2c_decision_logged"] = c2c
    details.append(f"  Debugging decision logged? → {c2c:.2f}")

    score = (c2a + c2b + c2c) / 3.0
    return {"score": round(score, 4), "criteria": criteria, "details": details}


# ── Circuit 3: Optimization ───────────────────────────────────────────

def score_circuit_3(model):
    """Validate query results against ground truth."""
    criteria = {}
    details = []

    status = tg('BENCH_MODEL_V2', [model, 3, "status"])
    if status != "done":
        return {"score": 0.0, "criteria": {"c3_status": 0.0}, "details": ["Model did not complete C3"]}

    cp_count = tg('BENCH_MODEL_V2', [model, 3, "cp_count"])
    avg_lat = tg('BENCH_MODEL_V2', [model, 3, "avg_lat"])
    top_street = tg('BENCH_MODEL_V2', [model, 3, "top_street"])
    max_id = tg('BENCH_MODEL_V2', [model, 3, "max_id"])

    # c3a: CP count — all are NULL so 1 unique (or model may handle NULL differently)
    ccp = safe_float(cp_count)
    c3a = 1.0 if ccp >= 1 else 0.0
    criteria["c3a_cp_count"] = c3a
    details.append(f"  Unique CPs: {cp_count} → {c3a:.2f}")

    # c3b: Average latitude — should be ~40.439
    lat = safe_float(avg_lat)
    lat_diff = abs(lat - GROUND_TRUTH["avg_lat"])
    c3b = max(0.0, 1.0 - lat_diff * 10)  # within 0.1 degrees = full points
    criteria["c3b_avg_latitude"] = round(c3b, 4)
    details.append(f"  Avg latitude: {avg_lat} (expected ~{GROUND_TRUTH['avg_lat']}) → {c3b:.2f}")

    # c3c: Top street type — should be "CALLE"
    ts = str(top_street).upper().strip('"\' ') if top_street else ''
    c3c = 1.0 if 'CALLE' in ts else 0.0
    criteria["c3c_top_street"] = c3c
    details.append(f"  Top street: {top_street} → {c3c:.2f}")

    # c3d: Max ID — should be ~MAD-621
    c3d = 1.0 if max_id and len(str(max_id)) > 3 else 0.0
    criteria["c3d_max_id"] = c3d
    details.append(f"  Max ID: {max_id} → {c3d:.2f}")

    score = (c3a + c3b + c3c + c3d) / 4.0
    return {"score": round(score, 4), "criteria": criteria, "details": details}


# ── Engine ────────────────────────────────────────────────────────────

SCORERS = {1: score_circuit_1, 2: score_circuit_2, 3: score_circuit_3}


def score_model(model):
    total_weighted = 0.0
    total_weight = 0.0
    results = {}

    for circuit in CIRCUITS:
        cid = circuit["id"]
        scorer = SCORERS.get(cid)
        if not scorer:
            continue
        result = scorer(model)
        weight = circuit["weight"]
        weighted = result["score"] * weight
        total_weighted += weighted
        total_weight += weight
        results[cid] = {
            "name": circuit["name"],
            "score": result["score"],
            "weight": weight,
            "weighted": round(weighted, 4),
            "criteria": result["criteria"],
            "details": result["details"],
        }

    final_score = round(total_weighted / total_weight, 4) if total_weight > 0 else 0.0
    return {"model": model, "final_score": final_score, "circuits": results}


def get_level(score):
    if score >= 0.90:
        return "🥇 LUMEN Architect"
    elif score >= 0.75:
        return "🥈 LUMEN Engineer"
    elif score >= 0.50:
        return "🥉 LUMEN Analyst"
    else:
        return "🔧 LUMEN Apprentice"


def show_report():
    models = get_models()
    if not models:
        print("=== LUMEN Cognitive Benchmark v2 — Judge ===\n")
        print("No models found in ^BENCH_MODEL_V2.")
        print()
        print("Available seeds:")
        print("  seed_farmacias_madrid.json (500 clean pharmacies)")
        print("  seed_farmacias_bugs.json (bug report for C2)")
        return

    print("=== LUMEN Cognitive Benchmark v2 — Judge ===\n")
    print(f"Found {len(models)} model(s)\n")

    all_results = {}
    for model in sorted(models):
        all_results[model] = score_model(model)

    header = f"{'Model':30s}"
    for circuit in CIRCUITS:
        header += f" | {circuit['name'][:12]:>12s}"
    header += " | {'Score':>7s} | {'Level':>20s}"
    print(header)
    print('-' * (30 + 16 * len(CIRCUITS) + 30))

    sorted_m = sorted(all_results.items(), key=lambda x: x[1]["final_score"], reverse=True)
    for rank, (model, result) in enumerate(sorted_m, 1):
        row = f"{model:30s}"
        for circuit in CIRCUITS:
            cid = circuit["id"]
            c = result.get("circuits", {}).get(cid, {})
            row += f" | {c.get('score', 0):>12.3f}"
        row += f" | {result['final_score']:>7.3f}"
        row += f" | {get_level(result['final_score']):>20s}"
        print(row)

    print()
    print("Levels: 🥇 LUMEN Architect (≥0.90) | 🥈 Engineer (≥0.75) | 🥉 Analyst (≥0.50) | 🔧 Apprentice (<0.50)")
    print("Circuits: Data Modeling 40% | Debugging 30% | Optimization 30%")


def show_detail(model):
    result = score_model(model)
    print(f"=== LUMEN Cognitive Benchmark v2 — {model} ===\n")
    print(f"Final Score: {result['final_score']:.3f} | {get_level(result['final_score'])}\n")

    for circuit in CIRCUITS:
        cid = circuit["id"]
        c = result.get("circuits", {}).get(cid, {})
        if not c:
            print(f"[{circuit['name']}] Not evaluated\n")
            continue
        print(f"[{circuit['name']}] score={c['score']:.3f} × weight={c['weight']} = {c['weighted']:.3f}")
        for d in c.get("details", []):
            print(f"  {d}")
        for crit_name, crit_val in c.get("criteria", {}).items():
            if crit_val is not None:
                print(f"    {crit_name}: {crit_val:.3f}")
        print()


def show_json():
    models = get_models()
    all_results = [score_model(m) for m in sorted(models)]
    print(json.dumps(all_results, indent=2, default=str))


if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == '--json':
            show_json()
        elif sys.argv[1] == '--detail' and len(sys.argv) > 2:
            show_detail(sys.argv[2])
        elif sys.argv[1] == '--help':
            print(__doc__)
        else:
            show_report()
    else:
        show_report()
