"""node_work.py — un nodo LUMEN/Hermes trabaja sobre tareas de un proyecto.

Modelo (migración lumen-002):
    organization -> project -> task -> lease -> event

Un nodo:
  1. pull    baja las tareas del proyecto + qué está ocupado (leases activos)
  2. lease   adquiere una tarea (si otro la tiene, 409 y NO la toca)
  3. trabaja (localmente: su PDB, su repo, su criterio)
  4. push    emite eventos (checkpoint, result_submitted) + cambio de estado
  5. release libera el lease

El resultado NO se duplica: el evento lleva `artifact_ref`/`hash` y el artefacto
se queda donde el nodo lo tenga.

Uso:
    python tools/node_work.py pull   --project <id> --node hermes-pc
    python tools/node_work.py lease  --project <id> --node hermes-pc --task <task_id>
    python tools/node_work.py done   --project <id> --node hermes-pc --task <id> --status done
    python tools/node_work.py status --project <id> --node hermes-pc
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://cadences.app/api/nodes/sync"
UA = "Mozilla/5.0 (compatible; lumen-node-work/1.0)"
STATE = pathlib.Path.home() / ".lumen-node-state.json"


# ── clave y transporte ───────────────────────────────────────────────────

def load_key(key_file: str | None = None) -> str:
    if key_file:
        p = pathlib.Path(key_file)
        if not p.exists():
            raise SystemExit(f"No existe el fichero de clave: {p}")
        return p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    env = os.environ.get("CADENCES_NODE_KEY", "").strip()
    if env:
        return env
    p = pathlib.Path.home() / ".cadences-node.key"
    if p.exists():
        return p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    raise SystemExit("No hay clave: --key-file, $CADENCES_NODE_KEY o ~/.cadences-node.key")


def sign(secret: str, body: str, ts: str) -> str:
    return hmac.new(secret.encode(), (ts + body + secret).encode(), hashlib.sha256).hexdigest()


def call(endpoint: str, secret: str, payload: dict, timeout: float = 60.0) -> dict:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    ts = str(int(time.time()))
    req = urllib.request.Request(
        endpoint, data=body.encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "X-DDP-Timestamp": ts,
                 "X-DDP-HMAC": sign(secret, body, ts), "User-Agent": UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as x:
            return {"status": x.status, **json.loads(x.read().decode("utf-8", "replace"))}
    except urllib.error.HTTPError as e:
        try:
            return {"status": e.code, **json.loads(e.read().decode("utf-8", "replace"))}
        except Exception:
            return {"status": e.code, "error": "(sin JSON)"}
    except Exception as e:
        return {"status": 0, "error": f"{type(e).__name__}: {e}"}


# ── estado local del nodo (le boundaries que el nodo posee) ──────────────

def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"leases": {}, "seq": 0}


def save_state(st: dict) -> None:
    STATE.write_text(json.dumps(st, indent=2), encoding="utf-8")


def next_seq(st: dict) -> int:
    st["seq"] = int(st.get("seq", 0)) + 1
    return st["seq"]


# ── comandos ─────────────────────────────────────────────────────────────

def cmd_pull(a, key) -> int:
    r = call(a.endpoint, key, {"action": "pull", "node": a.node, "project_id": a.project})
    if not r.get("success"):
        print(f"FALLO status={r.get('status')} :: {r.get('error')}")
        return 1

    tasks = r.get("tasks") or []
    leases = {(l["task_id"]): l["node_id"] for l in (r.get("leases") or [])}
    print(f"Proyecto {a.project}: {len(tasks)} tareas, {len(r.get('edges') or [])} dependencias")
    if r.get("project"):
        print(f"  proyecto: {r['project'].get('name')} (v{r['project'].get('version')})")
    print()
    for t in tasks:
        ocupada = leases.get(t["id"])
        marca = f"⛔ ocupada por {ocupada}" if ocupada else "✅ libre"
        print(f"  [{t.get('status','?'):12}] v{t.get('version')} {t['id']}")
        print(f"      {t.get('title','')}")
        print(f"      {marca}")
    return 0


def cmd_lease(a, key) -> int:
    st = load_state()
    r = call(a.endpoint, key, {"action": "lease", "node": a.node,
                               "task_id": a.task, "ttl": a.ttl})
    if not r.get("success"):
        if r.get("status") == 409:
            print(f"⛔ NO puedes tomarla: {r.get('error')}")
            print("   (otro nodo la está trabajando; no la toques)")
        else:
            print(f"FALLO status={r.get('status')} :: {r.get('error')}")
        return 1
    st["leases"][a.task] = {"lease_id": r["lease_id"], "token": r["token"],
                            "expires_at": r["expires_at"]}
    save_state(st)
    accion = "renovado" if r.get("renewed") else "adquirido"
    print(f"✅ lease {accion} de {a.task} (id {r['lease_id']}, caduca {r['expires_at']})")
    return 0


def cmd_done(a, key) -> int:
    """Emite result/checkpoint + cambio de estado, y libera el lease."""
    st = load_state()
    lease = st.get("leases", {}).get(a.task)
    if not lease:
        print("AVISO: no tienes lease de esa tarea. Tómala antes con 'lease'.")
        print("       (se enviará el evento igualmente, pero sin lease_id)")

    events = [{
        "id": f"evt_{int(time.time())}_{a.node}",
        "seq": next_seq(st),
        "type": "result_submitted",
        "project_id": a.project,
        "task_id": a.task,
        "lease_id": lease["lease_id"] if lease else None,
        "payload": {
            "status": a.status,
            "checkpoint": a.checkpoint or "",
            "artifact_ref": a.artifact or "",       # dónde está el resultado
            "artifact_hash": a.hash or "",
        },
        "idempotency_key": f"{a.node}:{a.task}:{a.status}:{int(time.time())}",
    }]
    tasks = [{"id": a.task, "project_id": a.project, "title": a.title or a.task,
              "spec": a.spec or "", "status": a.status, "priority": a.priority or "",
              "version": a.version or 1, "assignee": a.node}]

    r = call(a.endpoint, key, {"action": "push", "node": a.node,
                               "project_id": a.project, "events": events, "tasks": tasks})
    if not r.get("success"):
        print(f"FALLO status={r.get('status')} :: {r.get('error')}")
        return 1

    cf = r.get("conflicts") or []
    if cf:
        for c in cf:
            print(f"⚠️  CONFLICTO en {c['id']}: servidor v{c['server_version']} "
                  f"> local v{c['client_version']}")
            print("    No se sobrescribió. Recarga (pull) y reintenta con la versión buena.")
        return 2

    print(f"✅ resultado enviado: {a.task} -> {a.status}")
    for e in (r.get("events") or []):
        print(f"   evento {e.get('id')} {e.get('type')}")

    if lease:
        rr = call(a.endpoint, key, {"action": "release", "node": a.node,
                                    "task_id": a.task, "token": lease["token"]})
        if rr.get("success"):
            st.get("leases", {}).pop(a.task, None)
            save_state(st)
            print("✅ lease liberado: otro nodo puede tomarla")
        else:
            print(f"AVISO: no se pudo liberar el lease: {rr.get('error')}")
    return 0


def cmd_status(a, key) -> int:
    st = load_state()
    ls = st.get("leases") or {}
    print(f"Nodo {a.node} · leases activos: {len(ls)}")
    ahora = int(time.time())
    for tid, l in ls.items():
        resta = int(l.get("expires_at", 0)) - ahora
        estado = f"caduca en {resta}s" if resta > 0 else "CADUCADO"
        print(f"  {tid} -> {l.get('lease_id')} ({estado})")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Trabajar tareas de un proyecto como nodo")
    ap.add_argument("action", choices=["pull", "lease", "done", "status"])
    ap.add_argument("--project", required=False, default="")
    ap.add_argument("--node", default="hermes-pc")
    ap.add_argument("--task", default="")
    ap.add_argument("--ttl", type=int, default=900)
    ap.add_argument("--status", dest="status", default="done")
    ap.add_argument("--checkpoint", default="")
    ap.add_argument("--artifact", default="")
    ap.add_argument("--hash", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--spec", default="")
    ap.add_argument("--priority", default="")
    ap.add_argument("--version", type=int, default=1)
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--key-file", default=None)
    a = ap.parse_args(argv)

    if a.action in ("pull", "lease", "done") and not a.project:
        raise SystemExit("--project es obligatorio")
    if a.action in ("lease", "done") and not a.task:
        raise SystemExit("--task es obligatorio")

    key = load_key(a.key_file)
    return {"pull": cmd_pull, "lease": cmd_lease, "done": cmd_done, "status": cmd_status}[a.action](a, key)


if __name__ == "__main__":
    raise SystemExit(main())
