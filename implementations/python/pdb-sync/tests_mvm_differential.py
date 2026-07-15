#!/usr/bin/env python3
"""Golden differential: Python MVM and Tokio MVM observable globals."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PDB = ROOT / "implementations" / "mcp-servers" / "pdb"
GOLDEN = ROOT / "implementations" / "rust" / "lumen-mvm" / "tests" / "golden_jobs.json"

WORKER = r'''
import json, os, sys
import pdb_tools
from mvm import MVM

case = json.loads(sys.argv[1])
for entry in case["seed"]:
    pdb_tools.tool_set({"ns":"GOLDEN","subs":entry[:-1],"value":entry[-1]})
vm = MVM(pdb_tools)
if os.environ.get("MVM_ENGINE") == "rust":
    pid = vm.spawn(case["source"], name=case["name"], gas_limit=case["slice"])
else:
    pid = vm.spawn(case["source"], name=case["name"])
    vm.get_process(pid).gas_limit = case["slice"]
for _ in range(20):
    vm.tick_all(case["slice"])
    if vm.get_process(pid).status == "DEAD":
        break
values = [pdb_tools.tool_get({"ns":"GOLDEN","subs":subs}).get("value") for subs in case["checks"]]
print(json.dumps(values, ensure_ascii=False))
vm.close() if hasattr(vm, "close") else None
'''


def execute(engine, case):
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
            [sys.executable, "-c", WORKER, json.dumps(case)],
            env=environment,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])


cases = json.loads(GOLDEN.read_text(encoding="utf-8"))
passed = 0
for case in cases:
    try:
        python_result = execute("python", case)
        rust_result = execute("rust", case)
        assert python_result == rust_result == case["expected"], (
            python_result,
            rust_result,
            case["expected"],
        )
        passed += 1
        print(f"  ✅ {case['name']}")
    except Exception as error:
        print(f"  ❌ {case['name']}: {error}")

print(f"\n{passed}/{len(cases)} tests passed")
raise SystemExit(0 if passed == len(cases) else 1)
