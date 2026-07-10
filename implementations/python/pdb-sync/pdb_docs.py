#!/usr/bin/env python3
"""
pdb-docs — PDB Doc Engine: documentación viva sobre PDB jerárquica.

Supera los Magic Docs de Claude Code con:
- FTS5 full-text search
- Versionado automático ^docs("history")
- M-code ejecutable (flag executable=true)
- TTL inteligente + scoring
- Cross-refs a ^decisions, ^learnings
- Replicación edge nativa

Schema:
    ^docs("<ns>","<path>",...) = {
        content: "...",
        confidence: 1-10,
        source_agent: "hermes",
        last_commit: "abc123",
        executable: false,
        tags: [...],
        links: ["^decisions:1", "^learnings:42"],
        ttl: "24h"
    }

    ^docs("history","<ns>","<path>","<timestamp>") = <version anterior>

Uso:
    from pdb_docs import doc_set, doc_get, doc_search, doc_order

    doc_set("api", ["PRIVATE_REPO", "v1", "set"], {
        "content": "POST /v1/set/:ns — escribe en PDB...",
        "confidence": 9,
        "source_agent": "hermes"
    })

    results = doc_search("endpoint SET")

Author: Hermes + CadencesLab (CC6 — PDB Doc Engine)
Date: 2026-07-11
License: MIT (lumen-protocol)
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

# ── Config ──────────────────────────────────────────────────────────

PDB_PATH = os.path.expanduser(
    "~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb/lumen-pdb.db"
)

DOCS_NAMESPACE = "docs"
HISTORY_NAMESPACE = "docs_history"

# ── D2: TTL Policies (por tipo de documento) ────────────────────────

# TTL en segundos. None = no expira.
DOC_TTL = {
    "code":        0,          # invalidación inmediata (git commit)
    "api":         3600,       # 1 hora
    "decisions":   86400,      # 24 horas
    "architecture": 86400,     # 24 horas
    "guides":      259200,     # 72 horas
    "playbook":    None,       # no expira (conocimiento operativo)
    "default":     604800,     # 7 días
}

def get_doc_ttl(ns: str) -> int | None:
    """Obtener TTL para un tipo de documento."""
    return DOC_TTL.get(ns, DOC_TTL["default"])

def doc_is_stale(ns: str, subs: list) -> bool:
    """Verificar si un documento está obsoleto según su TTL."""
    doc = doc_get(ns, subs)
    if not doc:
        return False

    ttl = get_doc_ttl(ns)
    if ttl is None:
        return False  # playbooks no expiran
    if ttl == 0:
        return True   # code docs siempre stale hasta git hook

    updated_at = doc.get("updated_at", doc.get("created_at", ""))
    if not updated_at:
        return True

    from datetime import datetime, timezone, timedelta
    try:
        doc_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - doc_time).total_seconds()
        return age > ttl
    except (ValueError, TypeError):
        return True

def doc_mark_stale(ns: str, subs: list):
    """Marcar un documento como 'stale'."""
    doc = doc_get(ns, subs)
    if doc:
        doc["stale"] = True
        doc["stale_since"] = _now_iso()
        return doc_set(ns, subs, doc)
    return {"success": False, "error": "not found"}

def doc_check_all_stale():
    """Verificar TODOS los documentos y marcar los obsoletos.
    Usar como cron cada 5 minutos.
    """
    tools = _get_pdb_tools()
    stale_count = 0
    checked = 0

    # Iterar sobre todos los namespaces en ^docs
    ns_list = doc_list(limit=100)
    for ns_entry in ns_list:
        ns = ns_entry.get("key", "")
        if not ns:
            continue
        docs = doc_list(ns=ns, limit=100)
        for d in docs:
            checked += 1
            path = d.get("key", "")
            if doc_is_stale(ns, [path]):
                doc_mark_stale(ns, [path])
                stale_count += 1

    return {"checked": checked, "stale": stale_count, "timestamp": _now_iso()}

def doc_touch(ns: str, subs: list):
    """Actualizar timestamp de lectura (resetea TTL)."""
    doc = doc_get(ns, subs)
    if doc:
        doc["last_read"] = _now_iso()
        doc["read_count"] = doc.get("read_count", 0) + 1
        doc.setdefault("stale", False)
        return doc_set(ns, subs, doc)
    return {"success": False, "error": "not found"}

# ── Helpers ──────────────────────────────────────────────────────────

def _get_pdb_tools():
    """Importar pdb_tools desde el path."""
    pdb_dir = os.path.expanduser(
        "~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"
    )
    if pdb_dir not in sys.path:
        sys.path.insert(0, pdb_dir)
    import pdb_tools
    return pdb_tools

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Core CRUD ────────────────────────────────────────────────────────

def doc_set(ns: str, subs: list, data: dict) -> dict:
    """
    SET ^docs(ns, subs...) = data

    Args:
        ns: Categoría del documento (ej: "api", "architecture", "playbook")
        subs: Ruta jerárquica (ej: ["PRIVATE_REPO", "v1", "set"])
        data: Contenido con metadatos {content, confidence, source_agent, ...}

    Returns:
        {"success": True, "path": "docs/api/PRIVATE_REPO/v1/set"}
    """
    tools = _get_pdb_tools()

    # Versionado: guardar versión anterior en history
    old = doc_get(ns, subs)
    if old and old.get("content"):
        ts = _now_iso()
        history_subs = ["history", ns] + subs + [ts]
        tools.tool_set({
            "ns": HISTORY_NAMESPACE,
            "subs": history_subs,
            "value": old
        })

    # Añadir metadatos automáticos
    data["updated_at"] = _now_iso()
    if "created_at" not in data:
        data["created_at"] = _now_iso()

    full_subs = [ns] + subs
    result = tools.tool_set({
        "ns": DOCS_NAMESPACE,
        "subs": full_subs,
        "value": data
    })

    return {
        "success": result.get("success", False),
        "path": f"docs/{ns}/{'/'.join(str(s) for s in subs)}",
        "error": result.get("error")
    }

def doc_get(ns: str, subs: list) -> Optional[dict]:
    """GET ^docs(ns, subs...)."""
    tools = _get_pdb_tools()
    full_subs = [ns] + subs
    result = tools.tool_get({
        "ns": DOCS_NAMESPACE,
        "subs": full_subs
    })
    if result.get("success") and result.get("value") is not None:
        return result["value"]
    return None

def doc_order(ns: str, subs: list, direction: int = 1) -> Optional[str]:
    """$ORDER(^docs(ns, subs...))."""
    tools = _get_pdb_tools()
    full_subs = [ns] + subs
    result = tools.tool_order({
        "ns": DOCS_NAMESPACE,
        "subs": full_subs,
        "direction": direction
    })
    if result.get("success"):
        return result.get("value")
    return None

def doc_kill(ns: str, subs: list):
    """KILL ^docs(ns, subs...)."""
    tools = _get_pdb_tools()
    full_subs = [ns] + subs
    return tools.tool_kill({
        "ns": DOCS_NAMESPACE,
        "subs": full_subs
    })

def doc_history(ns: str, subs: list, limit: int = 10) -> list:
    """Leer historial de versiones de un doc."""
    tools = _get_pdb_tools()
    results = []
    key = ""
    full_subs_start = ["history", ns] + subs + [""]
    count = 0
    while count < limit:
        next_key = tools.tool_order({
            "ns": HISTORY_NAMESPACE,
            "subs": full_subs_start if not key else ["history", ns] + subs + [key],
            "direction": 1
        })
        if not next_key or not next_key.get("success"):
            break
        key = next_key.get("value")
        if not key:
            break
        ver = tools.tool_get({
            "ns": HISTORY_NAMESPACE,
            "subs": ["history", ns] + subs + [key]
        })
        if ver.get("success") and ver.get("value") is not None:
            results.append({"timestamp": key, "data": ver["value"]})
        count += 1
    return results

# ── Search ───────────────────────────────────────────────────────────

def doc_search(query: str, limit: int = 10) -> list:
    """FTS5 search en ^docs."""
    tools = _get_pdb_tools()
    result = tools.tool_fts_search({
        "query": query,
        "limit": limit,
        "ns": DOCS_NAMESPACE
    })
    if result.get("success"):
        return result.get("results", [])
    return []

def doc_list(ns: Optional[str] = None, limit: int = 20) -> list:
    """Listar docs en un namespace."""
    tools = _get_pdb_tools()
    results = []
    start_key = [ns, ""] if ns else [""]
    current = ""
    count = 0
    while count < limit:
        next_result = tools.tool_order({
            "ns": DOCS_NAMESPACE,
            "subs": [ns, current] if ns and current else start_key if ns else [current],
            "direction": 1
        })
        if not next_result.get("success") or not next_result.get("value"):
            break
        current = next_result["value"]
        doc = doc_get(ns, [current]) if ns else tools.tool_get({
            "ns": DOCS_NAMESPACE,
            "subs": [current]
        })
        if doc:
            results.append({"key": current, "data": doc})
        count += 1
    return results

# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "set":
        ns = sys.argv[2]
        path = sys.argv[3]
        content = sys.argv[4] if len(sys.argv) > 4 else ""
        result = doc_set(ns, path.split("/"), {
            "content": content,
            "confidence": 8,
            "source_agent": "cli"
        })
        print(json.dumps(result, indent=2))

    elif cmd == "get":
        ns = sys.argv[2]
        path = sys.argv[3]
        result = doc_get(ns, path.split("/"))
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif cmd == "search":
        query = sys.argv[2]
        results = doc_search(query)
        for r in results:
            print(f"📄 {r.get('key', '?')}: {str(r.get('value', ''))[:100]}...")

    elif cmd == "list":
        ns = sys.argv[2] if len(sys.argv) > 2 else None
        results = doc_list(ns)
        for r in results:
            print(f"📄 {r['key']}")

    elif cmd == "history":
        ns = sys.argv[2]
        path = sys.argv[3]
        versions = doc_history(ns, path.split("/"))
        for v in versions:
            print(f"🕐 {v['timestamp']}: {str(v['data'].get('content', ''))[:80]}...")

    else:
        print("PDB Doc Engine — documentación viva sobre PDB jerárquica")
        print("Uso: python pdb_docs.py [set|get|search|list|history] ...")
        print("MIT — lumen-protocol")
