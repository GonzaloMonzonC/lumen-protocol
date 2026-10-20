"""node_tasks.py — puente entre las tareas del usuario y el trabajo de los nodos.

ADR-001: `tasks` es la VERDAD. El nodo no escribe ahí directamente.

  diff    qué está desincronizado y quién gana (front o nodo)
  import  tasks -> lumen_tasks   (el usuario crea/edita, el nodo lo ve)
  apply   lumen_tasks -> tasks   (el nodo propone; se aplica SOLO si el usuario
                                  no ha cambiado la tarea después)

Uso:
    python tools/node_tasks.py diff   --project <id>
    python tools/node_tasks.py import --project <id>
    python tools/node_tasks.py apply  --project <id> --task <task_id>
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

DEFAULT_ENDPOINT = "https://cadences.app/api/nodes/link-tasks"
UA = "Mozilla/5.0 (compatible; lumen-node-tasks/1.0)"


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


def cmd_diff(a, key) -> int:
    r = call(a.endpoint, key, {"action": "diff", "project_id": a.project})
    if not r.get("success"):
        print(f"FALLO status={r.get('status')} :: {r.get('error')}")
        return 1

    print(f"Proyecto {a.project}: {r['en_front']} en front · {r['en_nodo']} en nodo\n")

    sf = r.get("solo_en_front") or []
    sn = r.get("solo_en_nodo") or []
    ds = r.get("desincronizadas") or []

    if sf:
        print(f"⬇️  SOLO EN EL FRONT ({len(sf)}) — el nodo aún no las tiene (usa 'import'):")
        for t in sf:
            print(f"     {t['id']} · {t.get('title','')} · {t.get('status','')}")
    if sn:
        print(f"\n⬆️  SOLO EN EL NODO ({len(sn)}) — las creó el nodo (usa 'apply'):")
        for t in sn:
            print(f"     {t['id']} · {t.get('title','')} · {t.get('status','')}")
    if ds:
        print(f"\n⚠️  DESINCRONIZADAS ({len(ds)}) — difieren front y nodo:")
        for d in ds:
            f, n = d["front"], d["nodo"]
            print(f"     {d['id']}")
            print(f"        front: v{f['version']} {f['status']} ({f['norm']})")
            print(f"        nodo : v{n['version']} {n['status']} ({n['norm']})")
            print(f"        gana : {d['gana'].upper()}"
                  + ("  <- el usuario manda" if d["gana"] == "front" else "  <- propuesta más reciente"))
    if not (sf or sn or ds):
        print("✅ Todo sincronizado.")
    return 0


def cmd_import(a, key) -> int:
    r = call(a.endpoint, key, {"action": "import", "project_id": a.project})
    if not r.get("success"):
        print(f"FALLO status={r.get('status')} :: {r.get('error')}")
        return 1
    print(f"✅ {r.get('imported',0)} importadas, {r.get('skipped',0)} sin cambios "
          f"(de {r.get('total',0)} en el proyecto)")
    if r.get("note"):
        print(f"   {r['note']}")
    return 0


def cmd_apply(a, key) -> int:
    r = call(a.endpoint, key, {"action": "apply", "project_id": a.project, "task_id": a.task})
    if r.get("success"):
        ap = r.get("applied") or {}
        print(f"✅ aplicado en el front: {r['task_id']} -> {ap.get('status')} (v{ap.get('version')})")
        return 0
    print(f"⛔ NO aplicado: {r.get('error')}")
    if r.get("hint"):
        print(f"   -> {r['hint']}")
    if r.get("front_version"):
        print(f"   front v{r['front_version']} vs nodo v{r['node_version']}")
    if r.get("status") == 409:
        print("   (el usuario manda: su cambio es posterior y no se sobrescribe)")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Puente tasks <-> lumen_tasks")
    ap.add_argument("action", choices=["diff", "import", "apply"])
    ap.add_argument("--project", required=True)
    ap.add_argument("--task", default="")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--key-file", default=None)
    a = ap.parse_args(argv)
    if a.action == "apply" and not a.task:
        raise SystemExit("'apply' necesita --task <task_id>")
    key = load_key(a.key_file)
    return {"diff": cmd_diff, "import": cmd_import, "apply": cmd_apply}[a.action](a, key)


if __name__ == "__main__":
    raise SystemExit(main())
