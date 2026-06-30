#!/usr/bin/env python3
"""
LUMEN Cognitive Benchmark v4 — Judge Script

Scores models on the Agent Construction benchmark.
Reads ^BENCH_MODEL_V4 from PDB and evaluates 3 circuits:
  1. Planning & Scaffolding (30 points)
  2. Execution & Tool Diversity (40 points)
  3. Documentation & Persistence (30 points)

Usage:
  python judge_v4.py                  # Score all v4 models
  python judge_v4.py --detail <model>  # Detailed breakdown
  python judge_v4.py --json            # JSON output
"""

import sys, os, json

# Path to PDB
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "pdb_tools", os.path.join(os.path.dirname(__file__), "..", "pdb_tools.py"))
pdb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb)


def get_models():
    """Discover all v4 models from ^BENCH_MODEL_V4."""
    models = set()
    result = pdb.tool_order({"ns": "BENCH_MODEL_V4", "subs": [""]})
    if result.get("success"):
        key = result.get("value")
        while key:
            if key not in ("C", "mtmp"):
                models.add(key)
            result = pdb.tool_order({"ns": "BENCH_MODEL_V4", "subs": [key]})
            key = result.get("value") if result.get("success") else None
    return sorted(models)


def get_val(model, key, default=None):
    """Read a verification key from ^BENCH_MODEL_V4."""
    result = pdb.tool_get({
        "ns": "BENCH_MODEL_V4",
        "subs": [model, "C", key],
        "default": default
    })
    return result.get("value", default) if result.get("success") else default


def score_circuit1(model):
    """Score Planning & Scaffolding (30 points)."""
    score = 0.0
    details = {}

    # Niche check
    niches_result = pdb.tool_query({
        "sql": "SELECT subkey, value FROM _globals WHERE ns='STATE' AND CAST(subkey AS TEXT) LIKE 'global:niche:%'"
    })
    niche_found = False
    if niches_result.get("success"):
        for row in niches_result.get("rows", []):
            try:
                val = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
                if val.get("name") == "Repo Health Scanner":
                    niche_found = True
                    break
            except:
                pass
    details["niche_exists"] = niche_found
    if niche_found:
        score += 5

    # Tasks check
    tasks_val = get_val(model, "tasks_created")
    task_count = int(tasks_val) if tasks_val and str(tasks_val).isdigit() else 0
    details["tasks_created"] = task_count
    if task_count >= 4:
        score += 5
    elif task_count >= 1:
        score += 2

    # Wiki check
    wiki_found = False
    wiki_result = pdb.tool_query({
        "sql": "SELECT value FROM _globals WHERE ns='STATE' AND CAST(subkey AS TEXT) LIKE 'session:%:wiki:%'"
    })
    if wiki_result.get("success"):
        for row in wiki_result.get("rows", []):
            try:
                val = row.get("value", "")
                if isinstance(val, bytes):
                    val = val.decode()
                if isinstance(val, str):
                    data = json.loads(val)
                    content = data.get("content", "")
                    if len(content) >= 500:
                        wiki_found = True
                        break
            except:
                pass
    details["wiki_500chars"] = wiki_found
    if wiki_found:
        score += 5

    # Decisions
    dec_val = get_val(model, "decisions_logged")
    dec_count = int(dec_val) if dec_val and str(dec_val).isdigit() else 0
    details["decisions_logged"] = dec_count
    if dec_count >= 2:
        score += 5
    elif dec_count >= 1:
        score += 2

    # Patterns
    pat_val = get_val(model, "patterns_recorded")
    pat_count = int(pat_val) if pat_val and str(pat_val).isdigit() else 0
    details["patterns_recorded"] = pat_count
    if pat_count >= 2:
        score += 5
    elif pat_count >= 1:
        score += 2

    # Planning done flag
    if get_val(model, "planning_done") == "yes":
        score += 5

    return min(score, 30), details


CATEGORIES = [
    ("cat_filesystem", "Filesystem"),
    ("cat_pdb_write", "PDB Write"),
    ("cat_pdb_read", "PDB Read"),
    ("cat_mlight", "M-Light"),
    ("cat_terminal", "Terminal"),
    ("cat_writefile", "File Write"),
    ("cat_web", "Web"),
    ("cat_kanban", "Kanban"),
]


def score_circuit2(model):
    """Score Execution & Tool Diversity (40 points)."""
    score = 0.0
    details = {}

    # Tool categories
    cats_used = 0
    for key, label in CATEGORIES:
        val = get_val(model, key)
        count = int(val) if val and str(val).isdigit() else 0
        details[key] = count
        if count >= 1:
            cats_used += 1
    details["categories_used"] = cats_used

    if cats_used >= 6:
        score += 15
    elif cats_used >= 4:
        score += 10
    elif cats_used >= 2:
        score += 5

    # Total distinct tools
    total_val = get_val(model, "total_tools_used")
    total_tools = int(total_val) if total_val and str(total_val).isdigit() else 0
    details["total_tools"] = total_tools
    if total_tools >= 30:
        score += 10
    elif total_tools >= 20:
        score += 8
    elif total_tools >= 10:
        score += 4

    # ^REPO_SCAN namespace exists with data
    scan_nodes = 0
    # Use PDB query to count all entries in REPO_SCAN namespace
    try:
        query_result = pdb.tool_query({"sql": "SELECT COUNT(*) as cnt FROM _globals WHERE ns='REPO_SCAN'"})
        if query_result.get("success") and query_result.get("rows"):
            scan_nodes = int(query_result["rows"][0].get("cnt", 0))
    except:
        pass
    details["repo_scan_nodes"] = scan_nodes
    if scan_nodes >= 3:
        score += 10
    elif scan_nodes >= 1:
        score += 5

    # repo_scanner.py exists (check via filesystem)
    import os as _os
    scanner_path = _os.path.join(_os.path.dirname(__file__), "repo_scanner.py")
    scanner_exists = _os.path.exists(scanner_path)
    scanner_lines = 0
    if scanner_exists:
        with open(scanner_path) as f:
            scanner_lines = len(f.readlines())
    details["scanner_exists"] = scanner_exists
    details["scanner_lines"] = scanner_lines
    if scanner_exists and scanner_lines >= 50:
        score += 5
    elif scanner_exists:
        score += 2

    return min(score, 40), details


def score_circuit3(model):
    """Score Documentation & Persistence (30 points)."""
    score = 0.0
    details = {}

    # Persistence verified
    pv = get_val(model, "persistence_verified")
    details["persistence_verified"] = pv
    if pv == "yes":
        score += 8

    # Wiki updated
    wu = get_val(model, "wiki_updated")
    details["wiki_updated"] = wu
    if wu == "yes":
        score += 7

    # Tasks completed
    tasks_val = get_val(model, "tasks_completed")
    tasks_done = int(tasks_val) if tasks_val and str(tasks_val).isdigit() else 0
    details["tasks_completed"] = tasks_done
    if tasks_done >= 4:
        score += 8
    elif tasks_done >= 1:
        score += 4

    # Self-score (honest)
    self_val = get_val(model, "final_score_self")
    self_score = int(self_val) if self_val and str(self_val).isdigit() else 0
    details["self_score"] = self_score
    if 50 <= self_score <= 100:
        score += 4
    elif 0 < self_score < 50:
        score += 2

    # Total tools documented
    total_val = get_val(model, "total_tools_used")
    total_tools = int(total_val) if total_val and str(total_val).isdigit() else 0
    if total_tools >= 20:
        score += 3
    elif total_tools >= 10:
        score += 1

    return min(score, 30), details


def level(score):
    if score >= 0.90:
        return "🥇 Architect"
    elif score >= 0.70:
        return "🥈 Engineer"
    elif score >= 0.50:
        return "🥉 Analyst"
    elif score > 0:
        return "🔧 Apprentice"
    return "—"


def main():
    models = get_models()
    if not models:
        print("No v4 models found in ^BENCH_MODEL_V4.")
        print("Run the benchmark with a model first:")
        print("  cat bench-results/BENCH_COGNITIVE_V4_PROMPT.md")
        return

    detail_model = None
    json_out = False
    args = sys.argv[1:]
    if "--detail" in args:
        idx = args.index("--detail")
        if idx + 1 < len(args):
            detail_model = args[idx + 1]
    if "--json" in args:
        json_out = True

    results = {}
    for model in models:
        c1, d1 = score_circuit1(model)
        c2, d2 = score_circuit2(model)
        c3, d3 = score_circuit3(model)
        total = c1 + c2 + c3
        results[model] = {
            "total": total,
            "circuit1": c1,
            "circuit2": c2,
            "circuit3": c3,
            "details": {**d1, **d2, **d3},
        }

    if json_out:
        print(json.dumps(results, indent=2))
        return

    if detail_model and detail_model in results:
        r = results[detail_model]
        d = r["details"]
        print(f"\n{'='*60}")
        print(f"  {detail_model} — Detailed Breakdown")
        print(f"{'='*60}")
        print(f"  Total: {r['total']:.1f}/100 — {level(r['total']/100)}")
        print(f"\n  Circuit 1 — Planning ({r['circuit1']:.1f}/30):")
        print(f"    Niche found: {d.get('niche_exists')}")
        print(f"    Tasks created: {d.get('tasks_created')}")
        print(f"    Wiki ≥500 chars: {d.get('wiki_500chars')}")
        print(f"    Decisions: {d.get('decisions_logged')}")
        print(f"    Patterns: {d.get('patterns_recorded')}")
        print(f"\n  Circuit 2 — Execution ({r['circuit2']:.1f}/40):")
        print(f"    Categories used: {d.get('categories_used')}/8")
        for key, label in CATEGORIES:
            print(f"      {label}: {d.get(key, 0)}")
        print(f"    Total tools: {d.get('total_tools', 0)}")
        print(f"    REPO_SCAN nodes: {d.get('repo_scan_nodes', 0)}")
        print(f"    scanner.py: {d.get('scanner_exists')} ({d.get('scanner_lines', 0)} lines)")
        print(f"\n  Circuit 3 — Documentation ({r['circuit3']:.1f}/30):")
        print(f"    Persistence verified: {d.get('persistence_verified')}")
        print(f"    Wiki updated: {d.get('wiki_updated')}")
        print(f"    Tasks completed: {d.get('tasks_completed')}")
        print(f"    Self-score: {d.get('self_score')}")
        return

    # Summary table
    print(f"\n{'Model':<35} {'Total':>6} {'C1':>5} {'C2':>5} {'C3':>5}  Level")
    print("-" * 75)
    for model, r in sorted(results.items(), key=lambda x: -x[1]["total"]):
        pct = r["total"] / 100
        print(f"{model:<35} {r['total']:5.1f} {r['circuit1']:5.1f} {r['circuit2']:5.1f} {r['circuit3']:5.1f}  {level(pct)}")


if __name__ == "__main__":
    main()
