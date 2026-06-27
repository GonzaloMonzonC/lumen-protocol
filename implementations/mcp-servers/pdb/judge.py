"""
LUMEN Cognitive Benchmark — Judge (v1.0)
=========================================
Walks ^BENCH_MODEL in MAIN PDB and scores each model across 6 circuits.

Usage:
    python judge.py                  # Score all models and show report
    python judge.py --json           # Output as JSON
    python judge.py --detail <model> # Show detailed scoring per circuit

Scoring formula:
    Final = Σ(circuit_weight × circuit_score)
    circuit_score = Σ(criteria_met) / Σ(criteria_total)
"""

import os, sys, json
from pathlib import Path

# Ensure we're in the right directory and can import pdb_tools
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pdb_tools
from m_light import MEvaluator

# ── Circuit definitions ────────────────────────────────────────────────
CIRCUITS = [
    {"id": 1, "name": "PDB CRUD",         "weight": 0.25},
    {"id": 2, "name": "M-Light",          "weight": 0.20},
    {"id": 3, "name": "Cognitive",        "weight": 0.20},
    {"id": 4, "name": "Knowledge",        "weight": 0.15},
    {"id": 5, "name": "Kanban",           "weight": 0.10},
    {"id": 6, "name": "Integration",      "weight": 0.10},
]

VERIFICATION_EXPECTED = {
    # Expected values from the benchmark prompt
    "total_balance": 9300,    # 2500+800+1500+300+4200
    "client_count": 5,
    "premium_count": 3,
    "average_balance": 1860.0,  # 9300/5
    "new_balance_5": 3780,      # 4200*0.9
}


# ── Helpers ────────────────────────────────────────────────────────────

def tool_get(ns, subs):
    """Safely get a PDB value, return None if not found."""
    try:
        r = pdb_tools.tool_get({"ns": ns, "subs": subs})
        return r.get("value")
    except Exception:
        return None


def tool_order(ns, subs):
    """Safely get next subscript, return None if not found."""
    try:
        r = pdb_tools.tool_order({"ns": ns, "subs": subs})
        return r.get("value")
    except Exception:
        return None


def tool_data(ns, subs):
    """Check $DATA for a node."""
    try:
        r = pdb_tools.tool_data({"ns": ns, "subs": subs})
        return r.get("data")
    except Exception:
        return 0


def get_models():
    """Find all models that have run the cognitive benchmark via $ORDER."""
    models = []
    I = ''
    while True:
        r = tool_order('BENCH_MODEL', [I])
        if not r:
            break
        I = r
        if I.startswith('_'):
            continue
        models.append(I)
    return models


def safe_float(val, default=0.0):
    """Convert value to float safely."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ── Per-circuit scoring ────────────────────────────────────────────────

def score_circuit_1(model):
    """
    Circuit 1: PDB CRUD (25%)
    Validates: data exists, total balance, count, status.

    Criteria (each 0 or 1):
    - c1a: ^CLIENTES(1..5) exist with data
    - c1b: ^CLIENTES("total","saldo") == 9300
    - c1c: ^BENCH_MODEL({M},1,"count") == "5"
    - c1d: ^BENCH_MODEL({M},1,"status") == "done"
    """
    criteria = {}
    details = []

    # c1a — Check client records 1-5 exist with required fields
    client_fields = ["nombre", "ciudad", "saldo"]
    clients_ok = 0
    for cid in range(1, 6):
        all_fields = True
        for field in client_fields:
            val = tool_get('CLIENTES', [cid, field])
            if val is None:
                all_fields = False
                details.append(f"  ✗ ^CLIENTES({cid},{field!r}) = missing")
        if all_fields:
            clients_ok += 1
    c1a = 1.0 if clients_ok == 5 else clients_ok / 5.0
    criteria["c1a_clients_exist"] = c1a
    details.append(f"  Clients OK: {clients_ok}/5 → {c1a:.2f}")

    # c1b — Total balance
    total_val = tool_get('CLIENTES', ["total", "saldo"])
    expected_total = VERIFICATION_EXPECTED["total_balance"]
    if total_val is not None:
        total_float = safe_float(total_val)
        c1b = 1.0 if abs(total_float - expected_total) < 0.01 else 0.0
        details.append(f"  ^CLIENTES(\"total\",\"saldo\") = {total_val} (expected {expected_total}) → {c1b:.2f}")
    else:
        c1b = 0.0
        details.append(f"  ✗ ^CLIENTES(\"total\",\"saldo\") = missing → 0.0")
    criteria["c1b_total_correct"] = c1b

    # c1c — Verification count
    count = tool_get('BENCH_MODEL', [model, 1, "count"])
    c1c = 1.0 if count == "5" else 0.0
    criteria["c1c_verification_count"] = c1c
    details.append(f"  ^BENCH_MODEL(count) = {count!r} → {c1c:.2f}")

    # c1d — Status
    status = tool_get('BENCH_MODEL', [model, 1, "status"])
    c1d = 1.0 if status == "done" else 0.0
    criteria["c1d_status"] = c1d
    details.append(f"  ^BENCH_MODEL(status) = {status!r} → {c1d:.2f}")

    score = (c1a + c1b + c1c + c1d) / 4.0
    return {"score": round(score, 4), "criteria": criteria, "details": details}


def score_circuit_2(model):
    """
    Circuit 2: M-Light (20%)
    Validates: categories exist and are correct, average, premium count.
    """
    criteria = {}
    details = []

    # c2a — Categories correct
    expected_cats = {1: "PREMIUM", 2: "STANDARD", 3: "PREMIUM",
                     4: "BASIC", 5: "PREMIUM"}
    cats_ok = 0
    for cid, expected_cat in expected_cats.items():
        val = tool_get('CLIENTES', [cid, "categoria"])
        if val is not None and str(val).strip('"').upper() == expected_cat:
            cats_ok += 1
        else:
            details.append(f"  ✗ ^CLIENTES({cid},\"categoria\") = {val!r} (expected {expected_cat})")
    c2a = cats_ok / 5.0
    criteria["c2a_categories_correct"] = c2a
    details.append(f"  Categories OK: {cats_ok}/5 → {c2a:.2f}")

    # c2b — Average balance
    media = tool_get('BENCH_MODEL', [model, 2, "media"])
    expected_media = VERIFICATION_EXPECTED["average_balance"]
    if media is not None:
        media_float = safe_float(media)
        c2b = 1.0 if abs(media_float - expected_media) < 0.5 else 0.0
        details.append(f"  ^BENCH_MODEL(media) = {media} (expected {expected_media}) → {c2b:.2f}")
    else:
        c2b = 0.0
        details.append(f"  ✗ ^BENCH_MODEL(media) = missing → 0.0")
    criteria["c2b_average_correct"] = c2b

    # c2c — Premium count
    premium_count = tool_get('BENCH_MODEL', [model, 2, "premium_count"])
    c2c = 1.0 if safe_float(premium_count) == VERIFICATION_EXPECTED["premium_count"] else 0.0
    criteria["c2c_premium_count"] = c2c
    details.append(f"  ^BENCH_MODEL(premium_count) = {premium_count!r} → {c2c:.2f}")

    # c2d — Status
    status = tool_get('BENCH_MODEL', [model, 2, "status"])
    c2d = 1.0 if status == "done" else 0.0
    criteria["c2d_status"] = c2d
    details.append(f"  ^BENCH_MODEL(status) = {status!r} → {c2d:.2f}")

    score = (c2a + c2b + c2c + c2d) / 4.0
    return {"score": round(score, 4), "criteria": criteria, "details": details}


def score_circuit_3(model):
    """
    Circuit 3: Cognitive (20%)
    Validates: sequential_thinking was called (hard to verify directly),
    decision logged, pattern recorded.
    """
    criteria = {}
    details = []

    # c3a — Status (model confirmed they did it)
    status = tool_get('BENCH_MODEL', [model, 3, "status"])
    c3a = 1.0 if status == "done" else 0.0
    criteria["c3a_status"] = c3a
    details.append(f"  ^BENCH_MODEL(status) = {status!r} → {c3a:.2f}")

    # c3b — Decision exists (check ^DECISIONS)
    decisions_exist = tool_data('DECISIONS', [''])
    c3b = 1.0 if decisions_exist and decisions_exist > 0 else 0.0
    criteria["c3b_decision_logged"] = c3b
    details.append(f"  ^DECISIONS exists? → {c3b:.2f}")

    # c3c — Pattern exists (check ^PATTERNS)
    patterns_exist = tool_data('PATTERNS', [''])
    c3c = 1.0 if patterns_exist and patterns_exist > 0 else 0.5
    criteria["c3c_pattern_recorded"] = c3c
    details.append(f"  ^PATTERNS exists? → {c3c:.2f}")

    score = (c3a + c3b + c3c) / 3.0
    return {"score": round(score, 4), "criteria": criteria, "details": details}


def score_circuit_4(model):
    """
    Circuit 4: Knowledge (15%)
    Validates: wiki page created, Q&A logged, status.
    """
    criteria = {}
    details = []

    # c4a — Wiki title saved
    wiki_title = tool_get('BENCH_MODEL', [model, 4, "wiki_title"])
    c4a = 1.0 if wiki_title and len(str(wiki_title)) > 5 else 0.0
    criteria["c4a_wiki_title"] = c4a
    details.append(f"  ^BENCH_MODEL(wiki_title) = {wiki_title!r} → {c4a:.2f}")

    # c4b — Q&A question saved
    qa_q = tool_get('BENCH_MODEL', [model, 4, "qa_question"])
    c4b = 1.0 if qa_q and len(str(qa_q)) > 5 else 0.0
    criteria["c4b_qa_question"] = c4b
    details.append(f"  ^BENCH_MODEL(qa_question) = {qa_q!r} → {c4b:.2f}")

    # c4c — Status
    status = tool_get('BENCH_MODEL', [model, 4, "status"])
    c4c = 1.0 if status == "done" else 0.0
    criteria["c4c_status"] = c4c
    details.append(f"  ^BENCH_MODEL(status) = {status!r} → {c4c:.2f}")

    score = (c4a + c4b + c4c) / 3.0
    return {"score": round(score, 4), "criteria": criteria, "details": details}


def score_circuit_5(model):
    """
    Circuit 5: Kanban (10%)
    Validates: tasks created, status.
    """
    criteria = {}
    details = []

    # c5a — Task count
    task_count = tool_get('BENCH_MODEL', [model, 5, "task_count"])
    c5a = 1.0 if safe_float(task_count) >= 3 else 0.0
    criteria["c5a_task_count"] = c5a
    details.append(f"  ^BENCH_MODEL(task_count) = {task_count!r} → {c5a:.2f}")

    # c5b — Status
    status = tool_get('BENCH_MODEL', [model, 5, "status"])
    c5b = 1.0 if status == "done" else 0.0
    criteria["c5b_status"] = c5b
    details.append(f"  ^BENCH_MODEL(status) = {status!r} → {c5b:.2f}")

    score = (c5a + c5b) / 2.0
    return {"score": round(score, 4), "criteria": criteria, "details": details}


def score_circuit_6(model):
    """
    Circuit 6: Integration (10%)
    Validates: new balance, updated PDB, status.
    """
    criteria = {}
    details = []

    # c6a — New balance for client #5
    new_balance = tool_get('BENCH_MODEL', [model, 6, "new_balance"])
    expected_bal = VERIFICATION_EXPECTED["new_balance_5"]
    if new_balance is not None:
        bal_float = safe_float(new_balance)
        c6a = 1.0 if abs(bal_float - expected_bal) < 0.5 else 0.0
        details.append(f"  ^BENCH_MODEL(new_balance) = {new_balance} (expected {expected_bal}) → {c6a:.2f}")
    else:
        c6a = 0.0
        details.append(f"  ✗ ^BENCH_MODEL(new_balance) = missing → 0.0")
    criteria["c6a_new_balance"] = c6a

    # c6b — Check actual PDB update
    actual_saldo = tool_get('CLIENTES', [5, "saldo"])
    if actual_saldo is not None:
        actual_float = safe_float(actual_saldo)
        c6b = 1.0 if abs(actual_float - expected_bal) < 0.5 else 0.0
        details.append(f"  ^CLIENTES(5,\"saldo\") = {actual_saldo} → {c6b:.2f}")
    else:
        c6b = 0.0
        details.append(f"  ✗ ^CLIENTES(5,\"saldo\") = missing → 0.0")
    criteria["c6b_pdb_updated"] = c6b

    # c6c — Status
    status = tool_get('BENCH_MODEL', [model, 6, "status"])
    c6c = 1.0 if status == "done" else 0.0
    criteria["c6c_status"] = c6c
    details.append(f"  ^BENCH_MODEL(status) = {status!r} → {c6c:.2f}")

    score = (c6a + c6b + c6c) / 3.0
    return {"score": round(score, 4), "criteria": criteria, "details": details}


# ── Scoring engine ─────────────────────────────────────────────────────

SCORERS = {
    1: score_circuit_1,
    2: score_circuit_2,
    3: score_circuit_3,
    4: score_circuit_4,
    5: score_circuit_5,
    6: score_circuit_6,
}


def score_model(model):
    """Score a single model across all 6 circuits."""
    results = {}
    total_weighted = 0.0
    total_weight = 0.0

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

    return {
        "model": model,
        "final_score": final_score,
        "circuits": results,
        "completed": tool_get('BENCH_MODEL', [model, "complete"]) == "1",
        "total_circuits": tool_get('BENCH_MODEL', [model, "total"]),
    }


def get_level(score):
    """Map score to level."""
    if score >= 0.95:
        return "🥇 LUMEN Master"
    elif score >= 0.80:
        return "🥈 LUMEN Pro"
    elif score >= 0.60:
        return "🥉 LUMEN User"
    else:
        return "🔧 Novice"


# ── Report rendering ───────────────────────────────────────────────────

def show_report():
    """Score all models and display comparison table."""
    models = get_models()
    if not models:
        print("=== LUMEN Cognitive Benchmark — Judge ===\n")
        print("No models found in ^BENCH_MODEL.")
        print("Have models run the cognitive benchmark prompt yet?\n")
        print("Models that have run bench.py (raw speed):")
        bm = []
        I = ''
        while True:
            r = tool_order('BENCH', [I])
            if not r:
                break
            I = r
            if not I.startswith('_'):
                bm.append(I)
        for m in sorted(bm):
            print(f"  • {m}")
        print(f"\n({len(bm)} models in ^BENCH, 0 in ^BENCH_MODEL)")
        return

    print("=== LUMEN Cognitive Benchmark — Judge ===\n")
    print(f"Found {len(models)} model(s)\n")

    all_results = {}
    for model in sorted(models):
        all_results[model] = score_model(model)

    # Table header
    header = f"{'Model':30s}"
    for circuit in CIRCUITS:
        header += f" | {circuit['name'][:10]:>10s}"
    header += " | {'Score':>8s} | {'Level':>16s}"
    print(header)
    print('-' * (30 + 14 * len(CIRCUITS) + 28))

    # Table rows
    sorted_models = sorted(all_results.items(),
                          key=lambda x: x[1]["final_score"], reverse=True)
    for rank, (model, result) in enumerate(sorted_models, 1):
        row = f"{model:30s}"
        for circuit in CIRCUITS:
            cid = circuit["id"]
            if cid in result.get("circuits", {}):
                c_score = result["circuits"][cid]["score"]
                row += f" | {c_score:>10.3f}"
            else:
                row += f" | {'-':>10s}"
        row += f" | {result['final_score']:>8.3f}"
        row += f" | {get_level(result['final_score']):>16s}"
        print(row)

    print()
    print("Levels: 🥇 LUMEN Master (≥0.95) | 🥈 Pro (≥0.80) | 🥉 User (≥0.60) | 🔧 Novice (<0.60)")
    print("Weights per circuit: PDB CRUD 25% | M-Light 20% | Cognitive 20% | Knowledge 15% | Kanban 10% | Integration 10%")
    print()


def show_detail(model):
    """Show detailed scoring for a single model."""
    result = score_model(model)
    print(f"=== LUMEN Cognitive Benchmark — {model} ===\n")
    print(f"Final Score: {result['final_score']:.3f} | {get_level(result['final_score'])}")
    print(f"Completed: {result['completed']} | Circuits: {result['total_circuits']}\n")

    for circuit in CIRCUITS:
        cid = circuit["id"]
        c = result.get("circuits", {}).get(cid)
        if not c:
            print(f"[{circuit['name']}] Not evaluated\n")
            continue
        print(f"[{circuit['name']}] score={c['score']:.3f} × weight={c['weight']} = {c['weighted']:.3f}")
        for detail in c.get("details", []):
            print(f"  {detail}")
        print()


def show_json():
    """Output results as JSON."""
    models = get_models()
    all_results = []
    for model in sorted(models):
        all_results.append(score_model(model))
    print(json.dumps(all_results, indent=2, default=str))


# ── Entry point ────────────────────────────────────────────────────────

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
