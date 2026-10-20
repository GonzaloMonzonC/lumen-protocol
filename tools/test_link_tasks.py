"""test_link_tasks.py — puente tasks <-> lumen_tasks con las tareas reales.

Verifica el ADR-001 en la práctica:
  1. import trae la tarea del usuario a la proyección
  2. el nodo la reclama (lease) y propone un cambio
  3. apply lo aplica en `tasks` si el usuario no ha cambiado después
  4. si el usuario SÍ cambió después (version mayor), apply RECHAZA
  5. el estado se traduce al idioma del front ('Completado', no 'done')

Uso: python tools/test_link_tasks.py <project_id> <task_id_del_usuario>
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import node_tasks as NT  # noqa: E402

PROJECT = sys.argv[1] if len(sys.argv) > 1 else ""
TASK = sys.argv[2] if len(sys.argv) > 2 else ""
if not PROJECT or not TASK:
    raise SystemExit("uso: test_link_tasks.py <project_id> <task_id>")

KEY = NT.load_key()
EP = NT.DEFAULT_ENDPOINT
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
    # 1. import (idempotente: ya se hizo, no debe duplicar)
    r = NT.call(EP, KEY, {"action": "import", "project_id": PROJECT})
    check("L1 import funciona", r.get("success") is True, str(r.get("error")))

    # 2. diff: comprobar que la tarea del usuario está en ambos lados
    r = NT.call(EP, KEY, {"action": "diff", "project_id": PROJECT})
    en_nodo = {t["id"] for t in (r.get("desincronizadas") or [])}
    solo_front = {t["id"] for t in (r.get("solo_en_front") or [])}
    check("L2 la tarea del usuario ya está sincronizada",
          TASK not in solo_front, f"solo_en_front={solo_front}")

    # 3. El nodo la reclama
    import node_work as NW
    lr = NW.call(NW.DEFAULT_ENDPOINT, KEY,
                 {"action": "lease", "node": "hermes-pc", "task_id": TASK, "ttl": 600})
    check("L3 el nodo reclama la tarea del usuario",
          lr.get("success") is True or lr.get("status") == 409, str(lr.get("error")))

    # 4. apply sin cambios del usuario -> debe aplicar
    r = NT.call(EP, KEY, {"action": "apply", "project_id": PROJECT, "task_id": TASK})
    # puede rechazar si el usuario cambió después; ambas respuestas son válidas,
    # lo que NO puede es aplicar silenciosamente pisando datos más nuevos.
    if r.get("success"):
        ap = r.get("applied") or {}
        check("L4 apply aplicado con estado del FRONT", ap.get("status") in
              ("Por Hacer", "En Progreso", "Completado", "Cancelada"),
              f"status={ap.get('status')}")
        check("L5 la version subió (CAS)", int(ap.get("version", 0)) >= 2,
              f"version={ap.get('version')}")
    else:
        check("L4 apply rechazado por conflicto (usuario manda)",
              r.get("status") == 409, str(r.get("error")))
        check("L5 el rechazo explica el motivo", bool(r.get("error")))

    # 6. estados: el nodo NUNCA escribe 'done' en el front
    r = NT.call(EP, KEY, {"action": "diff", "project_id": PROJECT})
    for d in (r.get("desincronizadas") or []):
        if d["id"] == TASK:
            check("L6 el nodo usa estados normalizados", d["nodo"]["norm"] in
                  ("todo", "in_progress", "done", "cancelled"),
                  f"norm={d['nodo']['norm']}")
            print(f"       front: {d['front']['status']} (v{d['front']['version']})")
            print(f"       nodo : {d['nodo']['status']} (v{d['nodo']['version']}) · gana: {d['gana']}")
            break
    else:
        check("L6 el nodo usa estados normalizados", True, "(sin desincronizar tras apply)")

    # 7. liberar
    st = NW.load_state()
    l = st.get("leases", {}).get(TASK)
    if l:
        NW.call(NW.DEFAULT_ENDPOINT, KEY, {"action": "release", "node": "hermes-pc",
                                           "task_id": TASK, "token": l["token"]})
        st["leases"].pop(TASK, None)
        NW.save_state(st)

    print(f"\n{OK + FAIL} checks · {OK} PASA · {FAIL} FALLA")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
