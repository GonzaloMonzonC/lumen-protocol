#!/usr/bin/env python3
"""Microbenchmark reproducible del contrato núcleo SQLite vs redb.

Mide la misma API Python (`set`, `get`, `incr`) y el mismo patrón de commit
por operación en ambos motores. No mide M-Light, triggers, journal DDP ni red.

Uso:
    python3 benchmark_redb.py
    python3 benchmark_redb.py --iterations 10000 --json resultado.json
"""

import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _paths  # noqa: E402,F401
from lumen_pdb import RedbPDB, SqlitePDB, ensure_built  # noqa: E402
from pdb_tools import encode_subkey  # noqa: E402


def measure(name, count, operation):
    started = time.perf_counter()
    operation()
    elapsed = time.perf_counter() - started
    return {
        "name": name,
        "operations": count,
        "seconds": round(elapsed, 6),
        "ops_per_second": round(count / elapsed, 1),
        "microseconds_per_op": round(elapsed * 1_000_000 / count, 2),
    }


def exercise(engine, iterations):
    payload = {"text": "LUMEN🔥", "n": 42, "ok": True}
    results = []
    raw = json.dumps(payload, ensure_ascii=False).encode()
    pairs = [(encode_subkey(["bulk", i]), raw) for i in range(iterations)]
    results.append(measure("set_bulk_1_tx", iterations, lambda: engine.set_raw(
        "BENCH", pairs)))
    results.append(measure("set_commit", iterations, lambda: [
        engine.set("BENCH", [i], payload) for i in range(iterations)
    ]))
    reads = iterations * 4
    results.append(measure("get_existing", reads, lambda: [
        engine.get("BENCH", [i % iterations]) for i in range(reads)
    ]))
    results.append(measure("increment_commit", iterations, lambda: [
        engine.incr("COUNTER", ["n"], 1) for _ in range(iterations)
    ]))
    engine.flush()
    return results


def main():
    parser = argparse.ArgumentParser(description="Benchmark redb vs SQLite")
    parser.add_argument("--iterations", type=int, default=3000)
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args()
    if args.iterations < 100:
        parser.error("--iterations debe ser >= 100")
    if not ensure_built():
        print("❌ dylib redb no disponible (¿cargo?)")
        return 1

    tmp = tempfile.mkdtemp(prefix="lumen-pdb-bench-")
    engines = []
    try:
        engines = [
            SqlitePDB(os.path.join(tmp, "bench.db")),
            RedbPDB(os.path.join(tmp, "bench.redb")),
        ]
        report = {
            "benchmark": "lumen-pdb core API",
            "iterations": args.iterations,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "durability": {
                "sqlite": "WAL + synchronous=NORMAL",
                "redb": os.environ.get("LUMEN_PDB_DURABILITY", "eventual"),
            },
            "results": {},
        }
        print(f"Benchmark PDB · {args.iterations} escrituras/incrementos, "
              f"{args.iterations * 4} lecturas")
        for engine in engines:
            rows = exercise(engine, args.iterations)
            report["results"][engine.name] = rows
            print(f"\n{engine.name}")
            for row in rows:
                print(f"  {row['name']:18s} {row['ops_per_second']:>10.1f} ops/s "
                      f"({row['microseconds_per_op']:.2f} µs/op)")
        if args.json_path:
            target = Path(args.json_path)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
            print(f"\nJSON: {target}")
        return 0
    finally:
        for engine in engines:
            engine.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
