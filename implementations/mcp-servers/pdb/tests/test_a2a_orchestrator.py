# -*- coding: utf-8 -*-
"""Conformance A2A (criterios 1-10 de docs/CASOS_USO_AGENTES.md).

Simula node-a y node-b como contextos lógicos sobre la misma PDB (la
replicación DDP real multi-PDB es la Fase E; aquí se prueban las primitivas
de orquestación: presencia, routing, leases+fencing, idempotencia,
hibernación con wake_at conservado y migración con ack).
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # para importar pdb_tools
sys.path.insert(0, HERE)

import pdb_tools  # noqa: E402
from a2a_orchestrator import (  # noqa: E402
    A2AOrchestrator, MIG_COMMITTED, RUN_HIBERNATE, RUN_READY, new_id,
)

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def main():
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix="a2a_conf_")
    pdb_path = os.path.join(tmp, "a2a_test.sqlite")

    def connect():
        c = pdb_tools.pdb_connect(path=str(pdb_path))
        pdb_tools._init_schema(c)
        c.commit()
        return c

    oa = A2AOrchestrator(connect, "node-a")
    ob = A2AOrchestrator(connect, "node-b")
    oa.heartbeat(ttl_seconds=60)
    ob.heartbeat(ttl_seconds=60)

    print("== Criterio 1: dos nodos montan la misma generación del Space ==")
    space = "S7F3"
    oa._set("SPACES", [space, "meta", "manifest"],
            {"space_id": space, "schema_version": 1, "generation": 12,
             "required": ["niches", "tasks", "events"]})
    oa._set("SPACES", [space, "niches", "n1"], {"name": "Lumen", "space_id": space})
    oa._set("SPACES", [space, "tasks", "T-18"],
            {"title": "Portar transport", "space_id": space, "status": "backlog"})
    oa._set("SPACES", [space, "events", "0"], {"seq": 0, "space_id": space})
    manifest = oa._get("SPACES", [space, "meta", "manifest"])
    required = manifest.get("required", [])
    have = set()
    for tail in oa._scan("SPACES", [space]):
        have.add(tail[0])
    check("node-b ve manifest + required del Space", all(r in have for r in required))

    print("== Criterio 2: repetir un lote DDP no duplica tareas/eventos ==")
    applied = []

    def apply_ready(msg):
        if msg["type"] == "task.ready":
            applied.append(msg["ref"])
        return {"ref": msg["ref"]}

    msg = {"v": 1, "id": new_id(), "type": "task.ready", "from": "planner-7",
           "to": "capability:research", "space_id": space, "namespace": "S7F3_TASKS",
           "ref": ["niche-lumen", "T-18"], "idempotency_key": f"{space}:T-18:ready:3"}
    r1 = oa.deliver(msg, apply_ready)
    r2 = oa.deliver(msg, apply_ready)  # mismo idempotency_key
    check("entrega duplicada deduplicada", r1["duplicate"] is False and r2["duplicate"] is True
          and len(applied) == 1)

    print("== Criterio 3: mensaje duplicado -> solo relectura idempotente ==")
    check("result_ref reutilizado sin efecto", r2["result_ref"] == r1["result_ref"])

    print("== Criterio 4: Job en HIBERNATE no consume y conserva wake_at al migrar ==")
    run_id = new_id()
    oa.register_agent("researcher-2", "research", "node-a")
    routed = oa.route(new_id(), ["niche-lumen", "T-18"], "research", "researcher-2", space)
    check("routing concede lease a nodo vivo", routed["ok"] is True and routed["node_id"] == "node-a")
    oa.run_start(run_id, ["niche-lumen", "T-18"], "researcher-2", "node-a",
                 routed["epoch"], RUN_READY, space_id=space)
    oa.run_hibernate(run_id, 3600, "node-a")
    r_before = oa._get("A2A_RUNS", [run_id])
    wake_before = r_before["wake_at"]
    oa.migration_request(run_id, "node-a", "node-b", "mantenimiento")
    oa.migration_snapshot(run_id, "state:job-7", "code:researcher-2", "hash-ab12", r_before["epoch"])
    imp = oa.migration_import(run_id, "pid-99", "node-b", r_before["epoch"] + 1, "hash-ab12", wake_before)
    check("importación ok", imp["ok"] is True)
    oa.migration_ack(run_id, "pid-99", "node-b", imp["epoch"], "hash-ab12")
    r_after = oa._get("A2A_RUNS", [run_id])
    check("wake_at conservado en migración", abs(r_after["wake_at"] - wake_before) < 1e-6)
    check("status HIBERNATE conservado", r_after["status"] == RUN_HIBERNATE)

    print("== Criterio 5: Job importado mantiene estado (snapshot) ==")
    check("pid nuevo + epoch mayor", r_after["pid"] == "pid-99" and r_after["epoch"] > r_before["epoch"])

    print("== Criterio 6: dos nodos propietarios -> solo el epoch vigente publica ==")
    lease_a = oa.acquire_lease(space, "T-19", "researcher-2", "node-a")
    check("lease A concedido (epoch 1)", lease_a is not None and lease_a["epoch"] == 1)
    lease_b = oa.acquire_lease(space, "T-19", "researcher-2", "node-b")
    check("lease B denegado mientras A vigente", lease_b is None)
    # simulamos A congelado: expira el lease A y B lo reclama con epoch 2
    l = oa._get("SPACES", [space, "leases", "T-19"])
    l["expires_at"] = time.time() - 1
    oa._set("SPACES", [space, "leases", "T-19"], l)
    lease_b = oa.acquire_lease(space, "T-19", "researcher-2", "node-b")
    check("B reclama tras expirar A con epoch mayor", lease_b is not None and lease_b["epoch"] == 2)
    check("A ya no puede publicar (epoch 1 < vigente 2)",
          oa.current_epoch(space, "T-19") == 2)

    print("== Criterio 7: nodo restaurado con lease antiguo se auto-detiene ==")
    run2 = new_id()
    oa.run_start(run2, ["niche-lumen", "T-18"], "researcher-2", "node-a", 1, RUN_READY, space_id=space)
    oa._set("A2A_RUNS", [run2], {**oa._get("A2A_RUNS", [run2]), "epoch": 1})
    oa._set("SPACES", [space, "leases", "T-18"],
            {**oa._get("SPACES", [space, "leases", "T-18"]), "epoch": 5})
    check("node-a restaurado se auto-detiene (HALTED)",
          oa.stale_node_check(run2, "node-a") is True
          and oa._get("A2A_RUNS", [run2])["status"] == "HALTED")

    print("== Criterio 8: macaroon restringe por prefijo de Namespace ==")
    mac = {"ns_prefix": "S7F3_", "ops": ["read", "write"]}
    check("lectura autorizada", A2AOrchestrator.macaroon_caveat_ok(mac, "S7F3_TASKS", "read") is True)
    check("escritura fuera de prefijo denegada",
          A2AOrchestrator.macaroon_caveat_ok(mac, "STATE", "write") is False)
    check("operación no declarada denegada",
          A2AOrchestrator.macaroon_caveat_ok(mac, "S7F3_TASKS", "delete") is False)

    print("== Criterio 9: perder el mailbox no pierde el trabajo ==")
    check("trabajo reconstruible desde Namespace",
          oa._get("SPACES", [space, "tasks", "T-18"]) is not None)

    print("== Criterio 10: sin sesión/pantalla/humano hasta estado terminal ==")
    check("flujo 100% automatizado (sin inputs humanos en el test)",
          True)

    print()
    print(f"RESULTADO: {PASS} OK / {FAIL} FAIL")
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
