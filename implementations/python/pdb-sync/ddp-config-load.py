#!/usr/bin/env python3
"""
ddp-config-load.py — Carga la config DDP maestra (ddp.json) en la PDB.

Fuente de verdad: ddp.json (declarativo). Este script lo aplica a ^System("ddp")
y ^DDP("...") vía tool_set, de modo que CUALQUIER agente/nodo lee la misma
config desde la PDB (y la ve por DDP).

Estructura que escribe en la PDB:

  ^System("ddp")                      = {edge, sync, limits, version, loaded_at}
  ^System("ddp","links",<nombre>)     = {target, type, ip, port, timeout, ...}
  ^System("ddf")  (alias)             = no; solo "ddp"
  ^System("identidad",<nodo>)         = {hostname, ip, port, role, arch, capabilities}
  ^DDP("config","namespaces",<ns>)    = {direction, journal, mode, legacy}
  ^DDP("journal",<ns>)                = true  (solo los que tienen journal=true)
  ^DDP("config","meta")               = {loaded_at, version, source}

Uso:
    python ddp-config-load.py                  # carga y aplica (default)
    python ddp-config-load.py --dry-run        # muestra qué escribiría, sin tocar la PDB
    python ddp-config-load.py --show           # muestra la config DDP actual en la PDB
    python ddp-config-load.py --file otro.json # usa otro fichero fuente

Licencia: MIT (lumen-protocol)
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))

import _paths  # noqa: E402,F401  deja mcp-servers/pdb en sys.path
from pdb_tools import tool_get, tool_set  # noqa: E402

DEFAULT_JSON = os.path.join(_HERE, "ddp.json")

# tipo de enlace (pdb_ddp_config.LINK_TYPES)
LINK_TYPES = {"service-binding": 0, "http": 1, "shared-memory": 3, "internal": 4}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise ValueError("La raíz del JSON debe ser un objeto")
    for req in ("edge", "namespaces"):
        if req not in cfg:
            raise ValueError(f"Falta la sección obligatoria: '{req}'")
    # ddp.json se publica con marcadores ${VAR} en vez de IPs internas (el repo
    # es publico). Se resuelven al cargar en la PDB, para que lo que se guarde
    # sea el valor real del nodo y no la plantilla.
    return _expand_tree(cfg)


_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand(valor):
    if not isinstance(valor, str) or "${" not in valor:
        return valor

    def _sub(m):
        nombre, default = m.group(1), m.group(2)
        v = os.environ.get(nombre)
        if v:
            return v
        return default if default is not None else m.group(0)

    return _VAR.sub(_sub, valor)


def _expand_tree(obj):
    """Recorre la config y resuelve ${VAR} en todas las cadenas."""
    if isinstance(obj, str):
        return _expand(obj)
    if isinstance(obj, list):
        return [_expand_tree(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _expand_tree(v) for k, v in obj.items()}
    return obj


def _plan(cfg: dict) -> list[tuple]:
    """Devuelve [(ns, subs, value)] — el plan de escrituras a la PDB."""
    ops: list[tuple] = []
    version = cfg.get("version", "1")
    loaded = _now()

    # 1. Config global de sistema ^System("ddp")
    ops.append(("System", ["ddp"], {
        "version": version,
        "edge": cfg.get("edge", {}),
        "hub": cfg.get("hub", {}),
        "sync": cfg.get("sync", {}),
        "limits": cfg.get("limits", {}),
        "loaded_at": loaded,
        "source": "ddp.json",
    }))

    # 2. Enlaces ^System("ddp","links",<name>)
    for name, link in (cfg.get("links") or {}).items():
        val = dict(link)
        val["name"] = name
        if "type" in val and isinstance(val["type"], str):
            val["type"] = LINK_TYPES.get(val["type"], 0)
        val.setdefault("created", loaded)
        val["updated"] = loaded
        ops.append(("System", ["ddp", "links", name], val))

    # 3. Identidad de nodos ^System("identidad",<node>)
    for name, node in (cfg.get("nodes") or {}).items():
        val = dict(node)
        val["node"] = name
        val["updated"] = loaded
        val.setdefault("registered", loaded)
        ops.append(("System", ["identidad", name], val))

    # 4. Namespaces ^DDP("config","namespaces",<ns>)
    for ns, spec in (cfg.get("namespaces") or {}).items():
        val = dict(spec)
        val.setdefault("direction", "pull")
        val["updated"] = loaded
        ops.append(("DDP", ["config", "namespaces", ns], val))
        # 5. Flag de journal ^DDP("journal",<ns>)
        ops.append(("DDP", ["journal", ns], bool(spec.get("journal", False))))

    # 6. Meta ^DDP("config","meta")
    ops.append(("DDP", ["config", "meta"], {
        "version": version,
        "loaded_at": loaded,
        "source": "ddp.json",
        "namespaces": len(cfg.get("namespaces") or {}),
        "journal_on": sorted(n for n, s in (cfg.get("namespaces") or {}).items()
                             if s.get("journal")),
    }))
    return ops


def load(path: str, dry_run: bool = False) -> int:
    cfg = _load(path)
    ops = _plan(cfg)
    print(f"[ddp-config] Fuente: {path}")
    print(f"[ddp-config] Plan: {len(ops)} escrituras "
          f"({len(cfg.get('namespaces') or {})} namespaces, "
          f"{len(cfg.get('links') or {})} enlaces, "
          f"{len(cfg.get('nodes') or {})} nodos)")
    if dry_run:
        for ns, subs, val in ops:
            v = json.dumps(val, ensure_ascii=False)
            print(f"  ^ {ns}({'|'.join(subs)}) = {v[:120]}")
        print("[ddp-config] DRY-RUN: no se escribió nada.")
        return 0
    written = 0
    for ns, subs, val in ops:
        r = tool_set({"ns": ns, "subs": subs, "value": val})
        if r.get("success", True):
            written += 1
        else:
            print(f"  ✗ FALLO {ns}({'|'.join(subs)}): {r}")
    print(f"[ddp-config] OK — {written}/{len(ops)} escrituras aplicadas a la PDB.")
    return 0 if written == len(ops) else 1


def show() -> int:
    print("=== ^System(\"ddp\") ===")
    print(json.dumps(tool_get({"ns": "System", "subs": ["ddp"]}), ensure_ascii=False, indent=2)[:1200])
    print("\n=== ^DDP(\"config\",\"meta\") ===")
    print(json.dumps(tool_get({"ns": "DDP", "subs": ["config", "meta"]}), ensure_ascii=False, indent=2))
    print("\n=== Journal activos (^DDP(\"journal\")) ===")
    r = tool_get({"ns": "DDP", "subs": ["journal"]})
    print(json.dumps(r, ensure_ascii=False)[:800])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Carga la config DDP maestra en la PDB")
    ap.add_argument("--file", default=DEFAULT_JSON, help="Fichero JSON fuente (default ddp.json)")
    ap.add_argument("--dry-run", action="store_true", help="Mostrar el plan sin escribir")
    ap.add_argument("--show", action="store_true", help="Mostrar la config DDP actual en la PDB")
    args = ap.parse_args()
    if args.show:
        return show()
    return load(args.file, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
