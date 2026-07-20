#!/usr/bin/env python3
"""Poli Performance Benchmark — MVM throughput con patrones reales."""
import json, os, platform, statistics, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
PDB = REPO / "implementations" / "mcp-servers" / "pdb"
sys.path[:0] = [str(PDB)]

from lumen_mlight import _call, ensure_built

POLI_CORE = Path(os.environ.get("POLI_REPO", str(REPO.parent / "poli" / "src" / "core")))

def load(name):
    return (POLI_CORE / name).read_text(encoding="utf-8")

def measure(function, iterations=200, warmup=50):
    for _ in range(warmup):
        function()
    samples = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        function()
        samples.append((time.perf_counter_ns() - t0) / 1000)
    samples.sort()
    median = statistics.median(samples)
    p95 = samples[min(len(samples)-1, int(len(samples)*0.95))]
    return {"iterations": iterations, "median_us": round(median,3), "p95_us": round(p95,3), "ops_s": round(1_000_000/median)}

def run(source, routines, gas=50000):
    return _call("lm_execute_json", json.dumps({
        "source": source, "routines": routines,
        "globals": [], "vars": {}, "job_id": 0, "gas_limit": gas, "gas_budget": 0, "input": [],
    }))

def main():
    if not ensure_built(quiet=False):
        raise SystemExit("Rust cdylib no disponible")

    u = load("UTILS.mac")
    p = load("PERSONALITY.mac")
    w = load("WIKI.mac")
    d = load("DECISIONS.mac")
    t = load("THINKING.mac")

    metrics = {}

    # 1. Compilación básica
    metrics["compile_1line"] = {"rust": measure(lambda: run("S x=42", {}), 5000)}
    metrics["compile_4lines"] = {"rust": measure(lambda: run("S x=42\nS y=x+1\nS z=y*2", {}), 3000)}
    metrics["compile_routine"] = {"rust": measure(lambda: run("S x=1", {"UTILS": u}), 500)}

    # 2. Aritmética y loops
    metrics["for_100_int"] = {"rust": measure(lambda: run("S t=0 F i=1:1:100 S t=t+i", {}), 300)}
    metrics["for_1000_int"] = {"rust": measure(lambda: run("S t=0 F i=1:1:1000 S t=t+i", {}), 50)}
    metrics["math_ops"] = {"rust": measure(lambda: run("S a=1.5 S b=a*3.14 S c=b/2 S d=c+10 S e=d-5", {}), 2000)}

    # 3. $ORDER global (corazón de LIST)
    metrics["global_order_10"] = {"rust": measure(lambda: run(
        "S k=\"\" F  S k=$O(^G(k)) Q:k=\"\"  S v=$G(^G(k))",
        {}, gas=2000), 100)}
    metrics["global_order_100"] = {"rust": measure(lambda: run(
        "S k=\"\" F  S k=$O(^H(k)) Q:k=\"\"  S v=$G(^H(k))",
        {}, gas=20000), 20)}

    # 4. IF/ELSE/FOR DO block
    metrics["if_else_do"] = {"rust": measure(lambda: run(
        "S r=\"\" I $G(x)=\"\" D\n. S r=\"empty\"\nE D\n. S r=\"full\"",
        {}), 1000)}

    # 5. Pipeline SEED
    metrics["seed_pipeline"] = {"rust": measure(lambda: run(
        "S r=$$SEED^PERSONALITY D LIST^PERSONALITY(.all,\"\")",
        {"UTILS": u, "PERSONALITY": p}), 50)}

    # 6. WIKI SAVE
    metrics["wiki_save"] = {"rust": measure(lambda: run(
        "S id=$$SAVE^WIKI(\"Bench\",\"Content\",\"perf\",\"test\")",
        {"WIKI": w, "UTILS": u}), 200)}

    # 7. WIKI GET
    metrics["wiki_get"] = {"rust": measure(lambda: run(
        "S i=\"wiki_9999999999\" D GET^WIKI(i)",
        {"WIKI": w, "UTILS": u}), 200)}

    # 8. $H y conversiones
    metrics["horolog"] = {"rust": measure(lambda: run(
        "S h=$H S u=$$NOW^UTILS S i=$$NOWISO^UTILS",
        {"UTILS": u}), 500)}

    # 9. DECISIONS LOG
    metrics["decisions_log"] = {"rust": measure(lambda: run(
        "S id=$$LOG^DECISIONS(\"perf\",\"test\",\"justification\",\"[]\")",
        {"DECISIONS": d, "UTILS": u}), 200)}

    # 10. Pipeline completo
    metrics["full_pipeline"] = {"rust": measure(lambda: run(
        "S r=$$SEED^PERSONALITY D LIST^PERSONALITY(.all,\"\") "
        "S id1=$$SAVE^WIKI(\"MVM\",\"Desc\",\"hermes\",\"perf\") "
        "S id2=$$SAVE^WIKI(\"Poli\",\"Sistema\",\"zalo\",\"perf\") "
        "D RECENT^WIKI(5) D BYAUTHOR^WIKI(\"hermes\") "
        "S id=$$LOG^DECISIONS(\"poli\",\"bench\",\"perf test\",\"[]\")",
        {"PERSONALITY": p, "UTILS": u, "WIKI": w, "DECISIONS": d}), 20)}

    report = {
        "schema": "poli-benchmark-v1",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "mlight_engine": "Rust M-Light FFI (lumen_mlight.dll)",
        "poli_routines": sorted(r.name for r in POLI_CORE.glob("*.mac")),
        "metrics": metrics,
    }
    output = HERE / "benchmark_poli.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\n✔ Saved {output}")

if __name__ == "__main__":
    main()
