#!/usr/bin/env python3
"""
ddp_config_read.py — Lector de la config DDP maestra desde la PDB.

La config se carga con ddp-config-load.py (fuente ddp.json). Este módulo la LEE
de la PDB (^System("ddp"), ^DDP("config",...)) para que los scripts (ddp_sync,
crons) dejen de tener valores hardcodeados.

Uso:
    from ddp_config_read import edge_url, sync_config, namespaces, journal_on
    url = edge_url()                      # ^System("ddp","edge","url")
    ns_list = namespaces(direction="pull") # ['ROUTINE','Eval','STATE']
    if journal_on("FACTS"): ...
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for p in (_HERE, os.path.dirname(_HERE),
          r"C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\pdb"):
    if p not in sys.path:
        sys.path.insert(0, p)

import _paths  # noqa: E402,F401
from pdb_tools import tool_get, tool_order  # noqa: E402


def _get(ns, subs, default=None):
    try:
        r = tool_get({"ns": ns, "subs": subs})
        v = r.get("value")
        return v if v is not None else default
    except Exception:
        return default


def config():
    """Bloque ^System("ddp") completo (o {} si no se ha cargado)."""
    return _get("System", ["ddp"], {}) or {}


def edge_url():
    """URL del edge CF (fallback a env / default)."""
    cfg = config().get("edge", {}) or {}
    return (cfg.get("url")
            or os.environ.get("PDB_EDGE_URL")
            or "https://pdb-edge.example.workers.dev")


def hub_url():
    return (config().get("hub", {}) or {}).get("url", "")


def sync_config():
    return config().get("sync", {}) or {}


def batch_size(default=500):
    return int(sync_config().get("batch_size", default))


def namespaces(direction=None):
    """Namespaces configurados, opcionalmente filtrados por dirección."""
    out = []
    k = ""
    while True:
        r = tool_order({"ns": "DDP", "subs": ["config", "namespaces", k], "direction": 1})
        v = r.get("value")
        if v is None:
            break
        k = v
        spec = _get("DDP", ["config", "namespaces", k], {}) or {}
        if direction and spec.get("direction") not in (direction, "both"):
            continue
        out.append(k)
    return out


def journal_on(ns):
    """¿El namespace pasa por journal? (^DDP("journal", ns))."""
    return bool(_get("DDP", ["journal", ns], False))


if __name__ == "__main__":
    print("edge_url :", edge_url())
    print("hub_url  :", hub_url())
    print("batch    :", batch_size())
    print("pull ns  :", namespaces("pull"))
    print("push ns  :", namespaces("push"))
    print("journal  :", [n for n in namespaces() if journal_on(n)])
