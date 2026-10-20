"""node_sync.py — push/pull de turnos entre la PDB local y cadences.app.

La PDB local es la VERDAD. cadences.app es una PROYECCIÓN.
  push: sube turnos locales; el servidor rechaza con "conflicts" si otra fuente
        tiene una versión igual o más nueva (nunca sobrescribe a ciegas).
  pull: baja turnos del servidor y los fusiona en la PDB local SIN pisar los
        locales más nuevos.

Uso:
    python tools/node_sync.py push --node hermes-pc
    python tools/node_sync.py pull --node hermes-pc
    python tools/node_sync.py status

El secreto se resuelve igual que en node_link.py:
    --key-file > $CADENCES_NODE_KEY > ~/.cadences-node.key
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
UA = "Mozilla/5.0 (compatible; lumen-node-sync/1.0)"


# ── clave ────────────────────────────────────────────────────────────────

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
    raise SystemExit("No hay clave: usa --key-file, $CADENCES_NODE_KEY o ~/.cadences-node.key")


def sign(secret: str, body: str, ts: str) -> str:
    return hmac.new(secret.encode(), (ts + body + secret).encode(), hashlib.sha256).hexdigest()


def call(endpoint: str, secret: str, payload: dict, timeout: float = 60.0) -> dict:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    ts = str(int(time.time()))
    req = urllib.request.Request(
        endpoint, data=body.encode("utf-8"), method="POST",
        headers={
            "Content-Type": "application/json",
            "X-DDP-Timestamp": ts,
            "X-DDP-HMAC": sign(secret, body, ts),
            "User-Agent": UA,
        },
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


# ── acceso a la PDB local (reutiliza el server del nodo) ─────────────────

def _thinking_dir() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    return here.parent.parent / "implementations" / "mcp-servers" / "thinking"


def _load_thinking():
    """Carga server.py y team_session.py del nodo. La PDB viene de PDB_PATH.

    OJO: hay que llamar a server._load_state() explícitamente. Importar el
    módulo NO restaura el estado de la PDB (solo inicializa memoria vacía); sin
    esta llamada export_sessions() devuelve 0 turnos aunque la PDB los tenga.
    """
    d = _thinking_dir()
    for p in (str(d), str(d.parent)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import server
    import team_session
    if not team_session._store():
        server._load_state()
    return server, team_session


def export_sessions() -> list[dict]:
    """Turnos locales -> formato del endpoint (plano, con rev)."""
    _srv, ts = _load_thinking()
    out = []
    for sid, s in ts._store().items():
        c = s.get("contract") or {}
        cps = c.get("checkpoints") or []
        out.append({
            "id": sid,
            "objective": c.get("objective", ""),
            "criterion": c.get("criterion", ""),
            "state": ts.derive_state(s),
            "owner": ts.current_owner(s),
            "members": s.get("members") or [],
            "checkpoint": (cps[-1].get("note", "") if cps else ""),
            # rev = número de eventos de la traza: crece con el trabajo real
            "rev": max(1, len(c.get("history") or [])),
            "history": c.get("history") or [],
            "created_at": int(s.get("created_at") or time.time()),
        })
    return out


def import_sessions(rows: list[dict], node: str) -> dict:
    """Turnos del servidor -> PDB local, sin pisar los locales más nuevos."""
    _srv, ts = _load_thinking()
    store = ts._store()
    added = updated = skipped = 0

    for r in rows:
        sid = r.get("id")
        if not sid:
            continue
        local = store.get(sid)
        server_rev = int(r.get("rev") or 1)

        if local is not None:
            local_rev = max(1, len((local.get("contract") or {}).get("history") or []))
            if local_rev >= server_rev:
                skipped += 1
                continue

        # Construye/actualiza el turno local a partir de la proyección
        contract = {
            "contract_id": f"ctr_remote_{sid[-12:]}",
            "objective": r.get("objective", ""),
            "criterion": r.get("criterion", ""),
            "inputs": [], "outputs": [], "limits": [],
            "role": "", "author": r.get("node_id", ""),
            "created_at": r.get("created_at"),
            "claim_status": _state_to_claim(r.get("state")),
            "claimed_by": r.get("owner") or "",
            "claimed_at": r.get("updated_at"),
            "history": r.get("history") or [],
            "checkpoints": ([{"ts": r.get("updated_at"), "by": r.get("owner") or "?",
                              "note": r.get("checkpoint") or ""}]
                            if r.get("checkpoint") else []),
        }
        session = {
            "session_id": sid,
            "contract": contract,
            "members": r.get("members") or [node],
            "created_at": r.get("created_at") or time.time(),
            "notes": [f"importado de {r.get('node_id')}"],
        }
        if local is None:
            added += 1
        else:
            updated += 1
        store[sid] = session

    if added or updated:
        try:
            _srv._pdb_save_all()   # síncrono: garantiza que queda en disco
        except Exception as e:
            print(f"AVISO: no se pudo persistir: {e}")

    return {"added": added, "updated": updated, "skipped": skipped}


def _state_to_claim(state: str) -> str:
    s = (state or "").lower()
    if s == "corriendo":
        return "claimed"
    if s == "cerrado":
        return "done"
    if s == "bloqueado":
        return "rejected"
    return "free"


# ── comandos ─────────────────────────────────────────────────────────────

def cmd_push(a) -> int:
    sessions = export_sessions()
    if not sessions:
        print("No hay turnos locales que subir.")
        return 0
    print(f"Subiendo {len(sessions)} turno(s) como '{a.node}'...")
    r = call(a.endpoint, load_key(a.key_file), {"action": "push", "node": a.node, "sessions": sessions})
    if not r.get("success"):
        print(f"FALLO status={r.get('status')} :: {r.get('error')}")
        return 1
    ap, cf, rj = r.get("applied") or [], r.get("conflicts") or [], r.get("rejected") or []
    print(f"OK  aplicados={len(ap)}  conflictos={len(cf)}  rechazados={len(rj)}")
    for c in cf:
        print(f"  CONFLICTO {c['id']}: servidor rev={c['server_rev']} "
              f"(dueño {c['owner_on_server']}) vs local rev={c['client_rev']}")
        print("            -> no se sobrescribió. Sube con rev mayor o haz handoff.")
    for x in rj:
        print(f"  RECHAZADO {x.get('id')}: {x.get('reason')}")
    return 0


def cmd_pull(a) -> int:
    key = load_key(a.key_file)
    print(f"Pidiendo turnos de '{a.node}'...")
    r = call(a.endpoint, key, {"action": "pull", "node": a.node})
    if not r.get("success"):
        print(f"FALLO status={r.get('status')} :: {r.get('error')}")
        return 1
    rows = r.get("sessions") or []
    print(f"Recibidos {len(rows)} turno(s). Fusionando en la PDB local...")
    st = import_sessions(rows, a.node)
    print(f"OK  nuevos={st['added']}  actualizados={st['updated']}  sin cambios={st['skipped']}")
    return 0


def cmd_status(a) -> int:
    rows = export_sessions()
    print(f"Turnos locales: {len(rows)}")
    for r in rows[:20]:
        print(f"  [{r['state']:16}] {r['id']} · {r['objective'][:40]} · "
              f"mando: {r['owner'] or '—'} · rev {r['rev']}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="push/pull de turnos nodo <-> cadences.app")
    ap.add_argument("action", choices=["push", "pull", "status"])
    ap.add_argument("--node", default="hermes-pc")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--key-file", default=None)
    a = ap.parse_args(argv)
    return {"push": cmd_push, "pull": cmd_pull, "status": cmd_status}[a.action](a)


if __name__ == "__main__":
    raise SystemExit(main())
