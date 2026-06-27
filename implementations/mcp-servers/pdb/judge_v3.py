"""
LUMEN Cognitive Benchmark v3 — Judge (alpha)
=============================================
Evaluates filesystem indexing benchmark.

Usage:
    python judge_v3.py                  # Score all models
    python judge_v3.py --detail <model>  # Detailed breakdown
    python judge_v3.py --json            # JSON output
"""

import os, sys, json, re, math
from pathlib import Path
from collections import Counter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pdb_tools

CIRCUITS = [
    {"id": 1, "name": "Scan + Index",  "weight": 0.35},
    {"id": 2, "name": "Zero-Token Queries", "weight": 0.35},
    {"id": 3, "name": "Cognition + Action", "weight": 0.30},
]

# Ground truth from actual scan of lumen-protocol/
GROUND_TRUTH = {
    "total_files": 11145,
    "total_dirs": 1247,
    "total_size_mb": 819.4,
    "total_size_bytes": 859_000_000,  # approximate
    "top_extensions": {".o": 2349, ".ts": 1424, ".js": 1216, ".map": 550,
                       ".json": 373, ".md": 372, ".cjs": 138, ".py": 128},
    "largest_files_threshold_mb": 10,
    "no_ext_count": 3350,
}


# ── Helpers ────────────────────────────────────────────────────────────

def tg(ns, subs):
    try:
        r = pdb_tools.tool_get({"ns": ns, "subs": subs})
        return r.get("value")
    except:
        return None

def to(ns, subs):
    try:
        r = pdb_tools.tool_order({"ns": ns, "subs": subs})
        return r.get("value")
    except:
        return None

def td(ns, subs):
    try:
        r = pdb_tools.tool_data({"ns": ns, "subs": subs})
        return r.get("value", 0)
    except:
        return 0

def safe_float(v, default=0.0):
    if v is None: return default
    try: return float(v)
    except: return default


def get_models():
    models = []
    I = ''
    while True:
        r = to('BENCH_MODEL_V3', [I])
        if not r: break
        I = r
        if I and not I.startswith('_'):
            models.append(I)
    return models


def walk_global(ns, max_depth=3, max_samples=20):
    """Walk a ^GLOBAL structure sampling first N branches to determine depth."""
    shape = {"depth": 0, "leaf_count": 0, "field_names": set(), "sampled": True}
    remaining = [max_samples]  # mutable container for closure

    def _walk(subs, depth):
        if depth > max_depth or remaining[0] <= 0: return
        if depth > shape["depth"]: shape["depth"] = depth
        
        I = ''
        while remaining[0] > 0:
            r = to(ns, subs + [I])
            if not r: break
            I = r
            remaining[0] -= 1
            d = td(ns, subs + [I])
            if d in (1, 11):
                shape["leaf_count"] += 1
                if depth >= 1:
                    shape["field_names"].add(str(I))
            if d in (10, 11):
                _walk(subs + [I], depth + 1)

    _walk([], 0)
    shape["field_count"] = len(shape["field_names"])
    return shape


# ── Scoring ────────────────────────────────────────────────────────────

def score_circuit_1(model):
    """Scan + Index: structure, counts, coverage."""
    criteria = {}
    details = []

    status = tg('BENCH_MODEL_V3', [model, 1, "status"])
    global_name = tg('BENCH_MODEL_V3', [model, 1, "global_name"])
    total_files = tg('BENCH_MODEL_V3', [model, 1, "total_files"])
    total_size = tg('BENCH_MODEL_V3', [model, 1, "total_size"])
    total_dirs = tg('BENCH_MODEL_V3', [model, 1, "total_dirs"])

    if status != "done" or not global_name:
        return {"score": 0.0, "criteria": {"c1_status": 0.0}, "details": ["Model did not complete C1"]}

    gns = str(global_name).strip('\'" ').lstrip('^')

    # c1a: File count accuracy
    tf = safe_float(total_files)
    c1a = max(0, 1.0 - abs(tf - GROUND_TRUTH["total_files"]) / GROUND_TRUTH["total_files"] * 2)
    c1a = round(max(0, min(1, c1a)), 4)
    criteria["c1a_files_accuracy"] = c1a
    details.append(f"  Files reported: {total_files} (expected ~{GROUND_TRUTH['total_files']}) → {c1a:.2f}")

    # c1b: Structure analysis
    shape = walk_global(gns)
    ideal_depth = 2
    c1b_depth = min(1.0, shape["depth"] / ideal_depth)
    details.append(f"  Structure depth: {shape['depth']} → {c1b_depth:.2f}")
    criteria["c1b_depth"] = c1b_depth
    criteria["c1b_leaf_count"] = shape["leaf_count"]
    details.append(f"  Leaf count: {shape['leaf_count']}")

    # c1c: Decision logged
    dl = tg('BENCH_MODEL_V3', [model, 1, "decision_logged"])
    c1c = 1.0 if dl and str(dl).lower() in ('yes', '1', 'true') else 0.0
    criteria["c1c_decision_logged"] = c1c
    details.append(f"  Decision logged? → {c1c:.2f}")

    # c1d: Pattern recorded
    pr = tg('BENCH_MODEL_V3', [model, 1, "pattern_recorded"])
    c1d = 1.0 if pr and str(pr).lower() in ('yes', '1', 'true') else 0.0
    criteria["c1d_pattern_recorded"] = c1d
    details.append(f"  Pattern recorded? → {c1d:.2f}")

    score = (c1a + c1b_depth + c1c + c1d) / 4.0
    return {"score": round(score, 4), "criteria": criteria, "details": details}


def score_circuit_2(model):
    """Zero-Token Queries: verify query results."""
    criteria = {}
    details = []

    status = tg('BENCH_MODEL_V3', [model, 2, "status"])
    if status != "done":
        return {"score": 0.0, "criteria": {"c2_status": 0.0}, "details": ["Model did not complete C2"]}

    top_ext = tg('BENCH_MODEL_V3', [model, 2, "top_ext"])
    top_dir = tg('BENCH_MODEL_V3', [model, 2, "top_dir"])
    largest_files = tg('BENCH_MODEL_V3', [model, 2, "largest_files"])
    size_dist = tg('BENCH_MODEL_V3', [model, 2, "size_dist"])
    no_ext = tg('BENCH_MODEL_V3', [model, 2, "no_ext"])

    # c2a: Files without extension
    ne = safe_float(no_ext)
    ne_expected = GROUND_TRUTH["no_ext_count"]
    c2a = max(0, 1.0 - abs(ne - ne_expected) / ne_expected)
    c2a = round(max(0, min(1, c2a)), 4)
    criteria["c2a_no_ext"] = c2a
    details.append(f"  Files w/o ext: {no_ext} (expected {ne_expected}) → {c2a:.2f}")

    # c2b: Largest files count reported
    lf = safe_float(largest_files)
    c2b = 1.0 if lf >= 1 else 0.0
    criteria["c2b_largest_files"] = c2b
    details.append(f"  Largest files count: {largest_files} → {c2b:.2f}")

    # c2c: Size distribution reported
    sd = str(size_dist) if size_dist else ''
    c2c = 1.0 if len(sd) > 5 else 0.0
    criteria["c2c_size_distribution"] = c2c
    details.append(f"  Size distribution: {sd} → {c2c:.2f}")

    # c2d: Top extension reported
    te = str(top_ext) if top_ext else ''
    c2d = 1.0 if len(te) > 3 and ('.' in te or ':' in te) else 0.0
    criteria["c2d_top_extension"] = c2d
    details.append(f"  Top extension: {top_ext} → {c2d:.2f}")

    score = (c2a + c2b + c2c + c2d) / 4.0
    return {"score": round(score, 4), "criteria": criteria, "details": details}


def score_circuit_3(model):
    """Cognition + Action: wiki, kanban, cleanup analysis."""
    criteria = {}
    details = []

    status = tg('BENCH_MODEL_V3', [model, 3, "status"])
    if status != "done":
        return {"score": 0.0, "criteria": {"c3_status": 0.0}, "details": ["Model did not complete C3"]}

    wiki_title = tg('BENCH_MODEL_V3', [model, 3, "wiki_title"])
    cleanup = tg('BENCH_MODEL_V3', [model, 3, "cleanup_potential"])
    task_count = tg('BENCH_MODEL_V3', [model, 3, "task_count"])
    dl = tg('BENCH_MODEL_V3', [model, 3, "decision_logged"])
    pr = tg('BENCH_MODEL_V3', [model, 3, "pattern_recorded"])

    # c3a: Wiki created
    c3a = 1.0 if wiki_title and len(str(wiki_title)) > 5 else 0.0
    criteria["c3a_wiki_created"] = c3a
    details.append(f"  Wiki title: {wiki_title} → {c3a:.2f}")

    # c3b: Cleanup analysis
    cp = safe_float(cleanup)
    c3b = 1.0 if cp > 0 else 0.0
    criteria["c3b_cleanup_analyzed"] = c3b
    details.append(f"  Cleanup potential: {cleanup} bytes → {c3b:.2f}")

    # c3c: Tasks created
    tc = safe_float(task_count)
    c3c = min(1.0, tc / 3.0)
    criteria["c3c_tasks_created"] = c3c
    details.append(f"  Tasks: {task_count} → {c3c:.2f}")

    # c3d: Decision logged
    c3d = 1.0 if dl and str(dl).lower() in ('yes', '1', 'true') else 0.0
    criteria["c3d_decision_logged"] = c3d
    details.append(f"  Decision logged? → {c3d:.2f}")

    # c3e: Pattern recorded
    c3e = 1.0 if pr and str(pr).lower() in ('yes', '1', 'true') else 0.0
    criteria["c3e_pattern_recorded"] = c3e
    details.append(f"  Pattern recorded? → {c3e:.2f}")

    score = (c3a + c3b + c3c + c3d + c3e) / 5.0
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
        if not scorer: continue
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
    if score >= 0.90: return "🥇 LUMEN Architect"
    elif score >= 0.75: return "🥈 LUMEN Engineer"
    elif score >= 0.50: return "🥉 LUMEN Analyst"
    else: return "🔧 LUMEN Apprentice"


def show_report():
    models = get_models()
    if not models:
        print("=== LUMEN Cognitive Benchmark v3 — Judge ===\n")
        print("No models found in ^BENCH_MODEL_V3.")
        return

    print("=== LUMEN Cognitive Benchmark v3 — Judge ===\n")
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
    print("Levels: 🥇 Architect (≥0.90) | 🥈 Engineer (≥0.75) | 🥉 Analyst (≥0.50) | 🔧 Apprentice (<0.50)")


def show_detail(model):
    result = score_model(model)
    print(f"=== LUMEN Cognitive Benchmark v3 — {model} ===\n")
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
        print()


def show_json():
    models = get_models()
    all_results = [score_model(m) for m in sorted(models)]
    print(json.dumps(all_results, indent=2, default=str))


if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == '--json': show_json()
        elif sys.argv[1] == '--detail' and len(sys.argv) > 2: show_detail(sys.argv[2])
        elif sys.argv[1] == '--help': print(__doc__)
        else: show_report()
    else:
        show_report()
