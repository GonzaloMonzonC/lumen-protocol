#!/usr/bin/env python3
"""Reproducible Fase 6 scheduler benchmark on the canonical SQLite PDB."""

import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
PDB = REPO / "implementations" / "mcp-servers" / "pdb"

WORKER = r'''
import json, time
import pdb_tools
from mvm import MVM

COUNT = 50
CODE = "S a=1\nS b=a+1\nS c=b+1\nS d=c+1\nS e=d+1"
vm = MVM(pdb_tools)

start = time.perf_counter()
pids = [vm.spawn(CODE, name=f"bench-{index}") for index in range(COUNT)]
spawn_seconds = time.perf_counter() - start

start = time.perf_counter()
vm.tick_all(20)
tick_seconds = time.perf_counter() - start

readers = [vm.spawn("R msg", name=f"reader-{index}") for index in range(COUNT)]
vm.tick_all(20)
start = time.perf_counter()
for pid in readers:
    vm.mailbox_send(pid, "ping")
mailbox_seconds = time.perf_counter() - start

start = time.perf_counter()
vm.close() if hasattr(vm, "close") else None
vm = MVM(pdb_tools)
restore_seconds = time.perf_counter() - start

print(json.dumps({
    "jobs": COUNT,
    "spawn_seconds": spawn_seconds,
    "spawn_jobs_s": COUNT / spawn_seconds,
    "tick_seconds": tick_seconds,
    "tick_jobs_s": COUNT / tick_seconds,
    "mailbox_seconds": mailbox_seconds,
    "mailbox_messages_s": COUNT / mailbox_seconds,
    "restore_seconds": restore_seconds,
    "restored_jobs": len(vm.list_processes()),
}))
vm.close() if hasattr(vm, "close") else None
'''


def run(engine):
    with tempfile.TemporaryDirectory() as directory:
        environment = os.environ.copy()
        environment.update(
            {
                "MVM_ENGINE": engine,
                "PDB_PATH": str(Path(directory) / f"{engine}.db"),
                "PYTHONPATH": str(PDB),
            }
        )
        result = subprocess.run(
            [sys.executable, "-c", WORKER],
            env=environment,
            text=True,
            capture_output=True,
            timeout=180,
            check=True,
        )
        return json.loads(result.stdout.strip().splitlines()[-1])


def main():
    metrics = {"python": run("python"), "rust_tokio": run("rust")}
    report = {
        "schema": "lumen-mvm-benchmark-v1",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "storage": "SQLite via pdb_tools for both schedulers",
        "workload": "50 jobs x 5 local SET; 50 durable mailbox sends; restore",
        "metrics": metrics,
    }
    output = HERE / "benchmark_tokio_vs_python.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nSaved {output}")


if __name__ == "__main__":
    main()
