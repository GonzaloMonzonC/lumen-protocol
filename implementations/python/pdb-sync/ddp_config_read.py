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
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for p in (_HERE, os.path.dirname(_HERE),
          os.path.join(os.path.dirname(os.path.dirname(_HERE)), "mcp-servers", "pdb")):
    if p not in sys.path:
        sys.path.insert(0, p)

import _paths  # noqa: E402,F401
from pdb_tools import tool_get, tool_order  # noqa: E402

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand(valor):
    """Resuelve ${VAR} y ${VAR:-default} contra el entorno.

    ddp.json se publica con marcadores en vez de IPs internas (el repo es
    publico). Sin esto, el hub apuntaria literalmente a '${DDP_HUB_HOST:-...}'.
    Si la variable falta y no hay default, se deja el marcador tal cual para que
    el fallo sea visible en vez de silencioso.
    """
    if not isinstance(valor, str) or "${" not in valor:
        return valor

    def _sub(m):
        nombre, default = m.group(1), m.group(2)
        v = os.environ.get(nombre)
        if v:
            return v
        return default if default is not None else m.group(0)

    return _VAR.sub(_sub, valor)


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
    return (_expand(cfg.get("url"))
            or os.environ.get("PDB_EDGE_URL")
            or "https://pdb-edge.example.workers.dev")


def hub_url():
    return _expand((config().get("hub", {}) or {}).get("url", ""))


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
