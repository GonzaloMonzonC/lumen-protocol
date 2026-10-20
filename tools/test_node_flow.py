"""test_node_flow.py — ciclo completo de un nodo sobre un proyecto real.

Demuestra el modelo organization->project->task->lease->event:
  1. push de una tarea (nodo PC la publica en el proyecto)
  2. lease por PC           -> adquirido
  3. lease por ASUS         -> 409, NO puede (exclusión real entre nodos)
  4. push result por PC     -> evento + cambio de estado (CAS)
  5. release                -> ASUS ya puede
  6. lease por ASUS         -> adquirido
  7. verificación en D1 de que el evento quedó registrado

Se ejecuta contra producción. Imprime claro qué prueba cada paso.
"""
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import node_work as W  # noqa: E402

PROJECT = sys.argv[1] if len(sys.argv) > 1 else ""
if not PROJECT:
    raise SystemExit("uso: python test_node_flow.py <project_id>")

KEY = W.load_key()
EP = W.DEFAULT_ENDPOINT
TASK = f"task_nodeflow_{int(time.time())}"
OK = FAIL = 0


def check(name, cond, detail=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"PASA   {name}")
    else:
        FAIL += 1
        print(f"FALLA  {name}")
        if detail:
            print(f"       {detail}")


def main() -> int:
    # 1. publicar la tarea (PC)
    print(f"\n1. Publicando tarea de prueba: {TASK}")
    r = W.call(EP, KEY, {
        "action": "push", "node": "hermes-pc", "project_id": PROJECT,
        "tasks": [{"id": TASK, "project_id": PROJECT, "title": "Prueba ciclo nodo",
                   "spec": "verificar lease y eventos", "status": "pending",
                   "priority": "medium", "version": 1, "assignee": ""}],
        "events": [],
    })
    check("N1 tarea publicada", r.get("success") and not (r.get("conflicts") or []))

    # 2. lease por PC
    print("\n2. PC toma la tarea")
    r = W.call(EP, KEY, {"action": "lease", "node": "hermes-pc", "task_id": TASK, "ttl": 600})
    check("N2 PC adquiere lease", r.get("success") and r.get("acquired") is True,
          str(r.get("error")))
    pc_token = r.get("token")

    # 3. ASUS intenta lo mismo -> debe fallar
    print("\n3. ASUS intenta la misma tarea (debe fallar)")
    r = W.call(EP, KEY, {"action": "lease", "node": "hermes-asus", "task_id": TASK, "ttl": 600})
    check("N3 ASUS NO puede (tarea ocupada)", r.get("success") is False
          and r.get("status") == 409, str(r))

    # 4. PC publica resultado
    print("\n4. PC publica resultado")
    r = W.call(EP, KEY, {
        "action": "push", "node": "hermes-pc", "project_id": PROJECT,
        "events": [{"id": f"evt_{TASK}_done", "seq": 1, "type": "result_submitted",
                    "project_id": PROJECT, "task_id": TASK,
                    "payload": {"status": "done", "artifact_ref": "docs/informe.md",
                                "artifact_hash": "abc123"},
                    "idempotency_key": f"hermes-pc:{TASK}:done"}],
        "tasks": [{"id": TASK, "project_id": PROJECT, "title": "Prueba ciclo nodo",
                   "status": "done", "version": 2, "assignee": "hermes-pc"}],
    })
    check("N4 resultado aplicado", r.get("success")
          and len(r.get("events") or []) == 1
          and not (r.get("conflicts") or []), str(r.get("conflicts")))

    # 4b. idempotencia: mismo evento otra vez
    print("\n4b. Reintento del mismo evento (idempotencia)")
    r = W.call(EP, KEY, {
        "action": "push", "node": "hermes-pc", "project_id": PROJECT,
        "events": [{"id": f"evt_{TASK}_done", "seq": 1, "type": "result_submitted",
                    "project_id": PROJECT, "task_id": TASK, "payload": {},
                    "idempotency_key": f"hermes-pc:{TASK}:done"}],
        "tasks": [],
    })
    ev = (r.get("events") or [{}])[0]
    check("N5 reintento no duplica (idempotente)", ev.get("idempotent") is True)

    # 5. PC libera
    print("\n5. PC libera el lease")
    r = W.call(EP, KEY, {"action": "release", "node": "hermes-pc",
                         "task_id": TASK, "token": pc_token})
    check("N6 lease liberado", r.get("success") is True, str(r.get("error")))

    # 6. ASUS ahora sí
    print("\n6. ASUS toma la tarea liberada")
    r = W.call(EP, KEY, {"action": "lease", "node": "hermes-asus", "task_id": TASK, "ttl": 600})
    check("N7 ASUS adquiere tras la liberación", r.get("success") and r.get("acquired") is True,
          str(r.get("error")))

    # 7. el pull devuelve estado y ocupación
    print("\n7. Pull del proyecto")
    r = W.call(EP, KEY, {"action": "pull", "node": "hermes-asus", "project_id": PROJECT})
    tareas = {t["id"]: t for t in (r.get("tasks") or [])}
    leases = {l["task_id"]: l["node_id"] for l in (r.get("leases") or [])}
    check("N8 pull trae la tarea", TASK in tareas)
    check("N9 pull dice quién la tiene", leases.get(TASK) == "hermes-asus",
          f"leases={leases}")
    check("N10 pull trae el estado actualizado", tareas.get(TASK, {}).get("status") == "done",
          f"status={tareas.get(TASK, {}).get('status')}")

    print(f"\n{OK + FAIL} checks · {OK} PASA · {FAIL} FALLA")
    print(f"\nTarea de prueba: {TASK} (proyecto {PROJECT})")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
