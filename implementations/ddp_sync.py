#!/usr/bin/env python3
"""
ddp_sync.py — wrapper de compatibilidad sobre la suite pdb-sync (Fase 2).

DEPRECATED: la implementación canónica de DDP es la suite pdb-sync
(pdb_ddp_client.DDPClient + pdb_sync_engine.SyncEngine + pdb_journal).
Este módulo conserva la API que usa ddp_cron.py (sync_pull, get_sync_ts,
set_sync_ts) y una CLI mínima. No añadir funcionalidad aquí.

Cambios vs la versión antigua:
- sync_push ya NO es no-op: usa SyncEngine.push_pending (journal seq +
  cursor "push", at-least-once).
- apply vía tool_set (contrato Fase 1b) — la versión antigua insertaba
  subkeys crudos en _globals, ilegibles para $ORDER.
- estado de sync en ^DDP("sync",ns,kind) vía tools (antes raw SQL).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

_SYNC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "python", "pdb-sync")
if _SYNC_DIR not in sys.path:
    sys.path.insert(0, _SYNC_DIR)

import _paths  # noqa: E402,F401  # deja mcp-servers/pdb en sys.path
from pdb_ddp_client import DDPClient  # noqa: E402
from pdb_sync_engine import SyncEngine  # noqa: E402
from pdb_tools import tool_get, tool_set, pdb_connect  # noqa: E402

DEFAULT_NS = "ROUTINE"
# La versión antigua usaba EDGE_URL; DDPClient usa PDB_EDGE_URL. Respetamos ambas.
EDGE_URL = os.environ.get("EDGE_URL") or os.environ.get("PDB_EDGE_URL")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _engine() -> SyncEngine:
    return SyncEngine(ddp=DDPClient(edge_url=EDGE_URL))


# ── Sync state: ^DDP("sync", ns, kind) ──

def get_sync_ts(ns: str, kind: str = "last_pull_ts") -> str:
    """Último timestamp de pull. Migra el estado legacy (raw SQL) si existe."""
    r = tool_get({"ns": "DDP", "subs": ["sync", ns, kind]})
    if r.get("value"):
        return r["value"]
    # legacy: fila cruda con subkey utf-8 "DDP:sync:{ns}:{kind}"
    try:
        c = pdb_connect(readonly=True)
        row = c.execute("SELECT value FROM _globals WHERE ns='DDP' AND subkey=?",
                        (f"DDP:sync:{ns}:{kind}".encode(),)).fetchone()
        c.close()
        if row:
            ts = json.loads(row[0])
            set_sync_ts(ns, ts, kind)  # migrar a la forma nueva
            return ts
    except Exception:
        pass
    return "1970-01-01T00:00:00Z"


def set_sync_ts(ns: str, ts: str, kind: str = "last_pull_ts"):
    tool_set({"ns": "DDP", "subs": ["sync", ns, kind], "value": ts})


# ── Operaciones ──

def sync_pull(ns: str = DEFAULT_NS) -> dict:
    """Pull de cambios del edge y aplicación local (vía SyncEngine)."""
    engine = _engine()
    since = get_sync_ts(ns)
    engine.last_sync[ns] = since
    print(f"[ddp] Pull {ns} desde {since}...")
    result = engine.pull_and_apply(ns)
    if "error" in result:
        print(f"[ddp] Pull error: {result['error']}")
        return {"pulled": 0, "error": result["error"]}
    applied = result.get("applied", 0)
    new_since = engine.last_sync.get(ns, since)
    if new_since != since:
        set_sync_ts(ns, new_since)
    print(f"[ddp] Pull: {applied} applied, {result.get('skipped', 0)} skipped (since -> {new_since})")
    return {"pulled": applied}


def sync_push(ns: str = DEFAULT_NS) -> dict:
    """Push de cambios locales pendientes (journal seq + cursor)."""
    result = _engine().push_pending(ns)
    if "error" in result:
        print(f"[ddp] Push error: {result['error']}")
        return {"pushed": 0, "error": result["error"]}
    pushed = result.get("applied", 0)
    print(f"[ddp] Push: {pushed} (cursor -> {result.get('cursor', 'sin cambios')})")
    return {"pushed": pushed}


def sync_all(ns: str = DEFAULT_NS):
    """Ciclo completo pull + push."""
    print(f"=== DDP Sync: {ns} @ {_now_iso()} ===")
    pull = sync_pull(ns)
    push = sync_push(ns)
    print(f"=== Sync: {pull.get('pulled', 0)} pulled, {push.get('pushed', 0)} pushed ===")
    return pull, push


# ── Main ──

def main():
    parser = argparse.ArgumentParser(description="DDP sync (wrapper sobre la suite pdb-sync)")
    parser.add_argument("command", choices=["pull", "push", "all", "status", "health"],
                        nargs="?", default="all")
    parser.add_argument("--ns", default=DEFAULT_NS)
    args = parser.parse_args()

    if args.command == "pull":
        print(json.dumps(sync_pull(args.ns)))
    elif args.command == "push":
        print(json.dumps(sync_push(args.ns)))
    elif args.command == "all":
        sync_all(args.ns)
    elif args.command == "status":
        print(json.dumps(_engine().ddp.status(), indent=2))
    elif args.command == "health":
        print(json.dumps(_engine().ddp.health(), indent=2))


if __name__ == "__main__":
    main()
