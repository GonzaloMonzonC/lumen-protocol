#!/usr/bin/env python3
"""Fase 5: shared golden and SQLite-boundary tests for Rust M-Light."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: F401

from lumen_mlight import (
    compile_source,
    ensure_built,
    execute,
    execute_sqlite,
    load_state,
    persist_sqlite_diff,
    save_state,
    snapshot_sqlite,
)
from pdb_tools import tool_apply_batch, tool_get, tool_kill, tool_m_eval, tool_set

passed = failed = 0


def test(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}")


print("🧪 TESTS M-LIGHT RUST (Fase 5)\n")

if not ensure_built():
    print("  ❌ dylib no compilable (falta cargo)")
    print("\n📊 0/1 tests passed")
    raise SystemExit(1)

golden_path = os.path.join(
    _paths.REPO,
    "implementations",
    "rust",
    "lumen-m-light",
    "tests",
    "golden_cases.json",
)
with open(golden_path, encoding="utf-8") as file:
    golden = json.load(file)

test("golden compartido contiene 8 casos", len(golden) == 8)
for case in golden:
    response = execute(
        case["source"], globals_=case.get("globals", []), gas_limit=10_000
    )
    state = response["state"]
    variables_match = all(
        state["vars"].get(name) == expected
        for name, expected in case.get("expected_vars", {}).items()
    )
    globals_match = not case.get("expected_globals") or (
        response["globals"] == case["expected_globals"]
    )
    test(
        f"golden {case['name']}",
        response["execution"] == case["execution"]
        and variables_match
        and globals_match
        and state["output"] == case.get("output", ""),
    )

program = compile_source("S a=1\nS b=2\nS c=3")
test(
    "bytecode versionado y SHA256",
    program["version"] == "3.0.0-rust" and len(program["source_hash"]) == 64,
)
first = execute(program=program, slice_gas=1, gas_limit=1)
test(
    "slice de gas cede con IP serializable",
    first["execution"] == "yielded"
    and first["state"]["ip"] == 1
    and first["state"]["gas_used"] == 1,
)
resumed = execute(
    program=program,
    state=json.loads(json.dumps(first["state"])),
    globals_=first["globals"],
    slice_gas=10,
)
test(
    "resume termina sin repetir instrucciones",
    resumed["execution"] == "completed"
    and resumed["state"]["vars"]["c"] == 3
    and resumed["state"]["gas_used"] == 3,
)
job_id = "conformance-rust"
test(
    "estado VM/gas persiste en ^STATE",
    save_state(job_id, first["state"]).get("success")
    and load_state(job_id) == first["state"],
)
tool_kill({"ns": "STATE", "subs": [job_id, "m_light_rust"]})

exhausted = execute("S a=1\nS b=2\nS c=3", gas_budget=2, slice_gas=10)
test(
    "gas_budget termina GAS_EXHAUSTED",
    exhausted["execution"] == "error"
    and exhausted["state"]["error"]["ecode"] == "GAS_EXHAUSTED",
)
job = execute("S seen=$J", job_id=42)
test("$J viaja en el estado serializable", job["state"]["vars"]["seen"] == 42)

namespace = "MLRUSTCONF"
tool_kill({"ns": namespace, "subs": []})
persisted = execute_sqlite(
    f'TSTART S ^{namespace}("keep")="sí" TCOMMIT\n'
    f'TSTART S ^{namespace}("discard")=2 TROLLBACK',
    gas_limit=100,
)
test(
    "adaptador persiste commit en SQLite vía pdb_tools",
    persisted["execution"] == "completed"
    and tool_get({"ns": namespace, "subs": ["keep"]}).get("value") == "sí",
)
test(
    "adaptador no persiste rollback",
    not tool_get({"ns": namespace, "subs": ["discard"]}).get("found", True),
)
tool_kill({"ns": namespace, "subs": []})

failed_batch = tool_apply_batch(
    {
        "operations": [
            {"op": "SET", "ns": namespace, "subs": ["partial"], "value": 1},
            {"op": "INVALID", "ns": namespace, "subs": ["never"]},
        ]
    }
)
test(
    "batch SQLite revierte todas las claves ante fallo",
    not failed_batch.get("success")
    and not tool_get({"ns": namespace, "subs": ["partial"]}).get("found", True),
)

tool_set({"ns": namespace, "subs": ["cas"], "value": 1})
before_conflict = snapshot_sqlite([namespace])
after_conflict = [
    {**entry, "value": 2} if entry.get("subs") == ["cas"] else entry
    for entry in before_conflict
]
tool_set({"ns": namespace, "subs": ["cas"], "value": 3})
try:
    persist_sqlite_diff(before_conflict, after_conflict)
    conflict_rejected = False
except RuntimeError as error:
    conflict_rejected = "PDB_CONFLICT" in str(error)
test(
    "snapshot rechaza lost update sobre la misma clave",
    conflict_rejected
    and tool_get({"ns": namespace, "subs": ["cas"]}).get("value") == 3,
)
tool_kill({"ns": namespace, "subs": []})

try:
    execute_sqlite('S ns="DYNAMIC",ref="^"_ns,value=@ref', persist=False)
    dynamic_rejected = False
except ValueError as error:
    dynamic_rejected = "namespaces" in str(error)
test("indirección dinámica exige namespaces explícitos", dynamic_rejected)

os.environ["MLIGHT_ENGINE"] = "rust"
flag_result = tool_m_eval({"expression": '$L("áβ")', "persist": False})
test(
    "MLIGHT_ENGINE=rust activa el StackVM Rust",
    flag_result.get("success")
    and flag_result.get("mode") == "rust_stackvm"
    and flag_result.get("result") == 2,
)
os.environ.pop("MLIGHT_ENGINE")

print(f"\n📊 {passed}/{passed + failed} tests passed")
raise SystemExit(0 if failed == 0 else 1)
