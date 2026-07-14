#!/usr/bin/env python3
"""
pdb_msasys.py — MSASYS: Configuración centralizada del ecosistema.

Inspirado en MSASYS (292 líneas) de MSM.

Un solo origen de verdad para toda la configuración:
  ^MSASYS("config", namespace, param) = valor
  ^MSASYS("default", namespace, param) = fallback
  ^MSASYS("version", namespace) = timestamp

Zalo: "Cuando algo falla, pierdes tiempo buscando dónde está el parámetro."
Solución: TODO en ^MSASYS. Nada en env vars para runtime.

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os
import _paths  # rutas repo-relativas
from datetime import datetime, timezone

MSASYS_NS = "MSASYS"

def _get_tools():
    pdb_dir = _paths.PDB_DIR_S
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get
    return tool_set, tool_get

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Default config ─────────────────────────────────────────────────

DEFAULTS = {
    "watchdog": {
        "interval_sec": 30,
        "timeout_sec": 120,
        "max_retries": 3,
        "primary": "hermes",
        "shadow": "lisa",
    },
    "agents": {
        "heartbeat_interval": 30,
        "session_timeout": 3600,
        "max_concurrent_tasks": 5,
        "max_response_time_ms": 5000,
    },
    "ddp": {
        "max_links": 16,
        "buffer_size": 1500,
        "circuit_timeout": 60,
        "retry_delay": 5,
    },
    "journal": {
        "batch_size": 50,
        "flush_interval": 10,
        "max_entries_before_rotate": 1000,
        "ttl_days": 30,
    },
    "rthist": {
        "snapshot_interval_min": 60,
        "retention_days": 7,
    },
}

# ── Init ───────────────────────────────────────────────────────────

def msasys_init():
    """Inicializar defaults si no existen."""
    tool_set, tool_get = _get_tools()
    
    for namespace, params in DEFAULTS.items():
        for param, value in params.items():
            r = tool_get({"ns": MSASYS_NS, "subs": ["config", namespace, param]})
            if not r.get("success") or r.get("value") is None:
                tool_set({"ns": MSASYS_NS, "subs": ["config", namespace, param], "value": value})
            tool_set({"ns": MSASYS_NS, "subs": ["default", namespace, param], "value": value})
        tool_set({"ns": MSASYS_NS, "subs": ["version", namespace], "value": _now_iso()})
    
    # Meta
    tool_set({"ns": MSASYS_NS, "subs": ["_meta"], "value": {
        "initialized": _now_iso(),
        "namespaces": list(DEFAULTS.keys()),
    }})
    
    return len(DEFAULTS)

# ── Get / Set ──────────────────────────────────────────────────────

def msasys_get(namespace, param):
    """Leer config con fallback automático a default."""
    _, tool_get = _get_tools()
    r = tool_get({"ns": MSASYS_NS, "subs": ["config", namespace, param]})
    if r.get("success") and r.get("value") is not None:
        return r["value"]
    # Fallback a default
    r2 = tool_get({"ns": MSASYS_NS, "subs": ["default", namespace, param]})
    if r2.get("success") and r2.get("value") is not None:
        return r2["value"]
    # Fallback a DEFAULTS en código
    return DEFAULTS.get(namespace, {}).get(param)

def msasys_set(namespace, param, value):
    """Escribir config."""
    tool_set, _ = _get_tools()
    tool_set({"ns": MSASYS_NS, "subs": ["config", namespace, param], "value": value})
    tool_set({"ns": MSASYS_NS, "subs": ["version", namespace], "value": _now_iso()})
    return value

def msasys_reset(namespace=None):
    """Reset a defaults (uno o todos los namespaces)."""
    tool_set, _ = _get_tools()
    namespaces = [namespace] if namespace else DEFAULTS.keys()
    for ns in namespaces:
        for param, value in DEFAULTS.get(ns, {}).items():
            tool_set({"ns": MSASYS_NS, "subs": ["config", ns, param], "value": value})
        tool_set({"ns": MSASYS_NS, "subs": ["version", ns], "value": _now_iso()})
    return list(namespaces)

# ── Report ─────────────────────────────────────────────────────────

def msasys_report():
    """Reporte completo de configuración."""
    data = {}
    for namespace in DEFAULTS:
        ns_data = {}
        for param in DEFAULTS[namespace]:
            val = msasys_get(namespace, param)
            default = DEFAULTS[namespace][param]
            ns_data[param] = {"value": val, "default": default, "modified": val != default}
        data[namespace] = ns_data
    return data

# ── CLI ──

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "init"
    
    if cmd == "init":
        n = msasys_init()
        namespaces = list(DEFAULTS.keys())
        print(f"✅ MSASYS: {n} namespaces ({', '.join(namespaces)})")
    
    elif cmd == "get":
        ns = sys.argv[2]; param = sys.argv[3]
        v = msasys_get(ns, param)
        print(f"  {ns}.{param} = {v}")
    
    elif cmd == "set":
        ns = sys.argv[2]; param = sys.argv[3]; val = sys.argv[4]
        msasys_set(ns, param, val)
        print(f"  ✅ {ns}.{param} = {val}")
    
    elif cmd == "report":
        for ns, params in msasys_report().items():
            print(f"\n📋 {ns}:")
            for p, info in params.items():
                icon = "✏️" if info['modified'] else "✅"
                print(f"   {icon} {p} = {info['value']}")
    
    elif cmd == "reset":
        ns = sys.argv[2] if len(sys.argv) > 2 else None
        r = msasys_reset(ns)
        print(f"  ✅ Reset: {', '.join(r)}")
