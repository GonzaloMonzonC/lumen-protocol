#!/usr/bin/env python3
"""Reproducible Fase 5 benchmark: Python v2 versus Rust JSON FFI."""

import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
SYNC = REPO / "implementations" / "python" / "pdb-sync"
PDB = REPO / "implementations" / "mcp-servers" / "pdb"
sys.path[:0] = [str(SYNC), str(PDB)]

from lumen_mlight import compile_source, ensure_built, execute  # noqa: E402
from m_light_compiler import MCompiler  # noqa: E402
from m_stackvm import StackVM  # noqa: E402


def measure(function, iterations, warmup=50):
    for _ in range(warmup):
        function()
    samples = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        function()
        samples.append((time.perf_counter_ns() - start) / 1000)
    samples.sort()
    median = statistics.median(samples)
    p95 = samples[min(len(samples) - 1, int(len(samples) * 0.95))]
    return {
        "iterations": iterations,
        "median_us": round(median, 3),
        "p95_us": round(p95, 3),
        "ops_s": round(1_000_000 / median),
    }


def main():
    if not ensure_built(quiet=False):
        raise SystemExit("Rust cdylib unavailable")

    one_line = "S x=42"
    four_lines = "S x=42\nS y=x+1\nS z=y*2\nW z"
    loop_rust = "S total=0\nF i=1:1:100 { S total=total+i }"
    loop_python = "S total=0\nF i=1:1:100 S total=total+i"
    rust_program = compile_source(four_lines)
    python_program = StackVM().compile(four_lines)

    metrics = {
        "compile_1_line": {
            "python": measure(lambda: MCompiler().compile(one_line), 5000),
            "rust_ffi": measure(lambda: compile_source(one_line), 5000),
        },
        "compile_4_lines": {
            "python": measure(lambda: MCompiler().compile(four_lines), 3000),
            "rust_ffi": measure(lambda: compile_source(four_lines), 3000),
        },
        "compile_and_execute_4_lines": {
            "python": measure(lambda: StackVM().compile(four_lines).exec(), 2000),
            "rust_ffi": measure(lambda: execute(four_lines, gas_limit=100), 2000),
        },
        "execute_precompiled_4_lines": {
            "python": measure(python_program.exec, 2000),
            "rust_ffi": measure(
                lambda: execute(program=rust_program, gas_limit=100), 2000
            ),
        },
        "for_100": {
            "python": measure(lambda: StackVM().compile(loop_python).exec(), 300),
            "rust_ffi": measure(lambda: execute(loop_rust, gas_limit=1000), 300),
        },
    }
    report = {
        "schema": "lumen-m-light-benchmark-v1",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "mlight_engine": "SQLite remains canonical; pure VM benchmark",
        "metrics": metrics,
    }
    output = HERE / "benchmark_rust_vs_python.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nSaved {output}")


if __name__ == "__main__":
    main()
