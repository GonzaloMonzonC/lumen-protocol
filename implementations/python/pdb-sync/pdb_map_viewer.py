#!/usr/bin/env python3
"""
pdb_map_viewer.py — MAPFCB: Mapa de namespaces PDB.

Inspirado en MAPFCB (237 líneas) de MSM.

Herramienta de diagnóstico que muestra:
  - Namespaces existentes con tamaño (entradas + bytes)
  - Estado (activo/archivado)
  - Relaciones entre namespaces
  - Último acceso

Zalo: "Saber qué ocupa espacio. Detectar corrupción temprano."

Esquema:
  ^PDBMAP("ns", nombre) = {entries, bytes, status, last_access}
  ^PDBMAP("refs", origen, destino) = count

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, json
from datetime import datetime, timezone

PDBMAP_NS = "PDBMAP"

def _get_tools():
    pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order
    return tool_set, tool_get, tool_order

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Scan ──────────────────────────────────────────────────────────

PDB_NAMESPACES = [
    "RTHIST", "MSASYS", "CSFMON", "LOGON", "System",
    "CHANGES", "DDP", "Agent", "BIJ", "docs",
    "ROUTINE", "TEST", "STRESS", "CLIMA", "COMPARE_TEST",
    "BIJ_TEST", "PROCESSES",
]

def map_scan_namespace(ns, limit=500):
    """Escanear un namespace: contar entradas y estimar bytes."""
    _, tool_get, tool_order = _get_tools()
    entries = 0
    key = ""
    sample_value = None
    while entries < limit:
        r = tool_order({"ns": ns, "subs": [key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        entries += 1
        if entries == 1:
            r2 = tool_get({"ns": ns, "subs": [key]})
            if r2.get("success") and r2.get("value"):
                sample_value = r2["value"]
    return entries, len(json.dumps(sample_value)) if sample_value else 0

def map_scan_all():
    """Escanear todos los namespaces y guardar en ^PDBMAP."""
    tool_set, _, _ = _get_tools()
    ts = _now_iso()
    total_entries = 0
    results = []
    
    for ns in PDB_NAMESPACES:
        try:
            entries, sample_bytes = map_scan_namespace(ns)
            status = "active" if entries > 0 else "empty"
            
            tool_set({"ns": PDBMAP_NS, "subs": ["ns", ns], "value": {
                "entries": entries,
                "status": status,
                "last_access": ts,
                "sample_bytes": sample_bytes,
            }})
            
            total_entries += entries
            results.append({"ns": ns, "entries": entries, "status": status})
        except Exception as e:
            tool_set({"ns": PDBMAP_NS, "subs": ["ns", ns], "value": {
                "entries": 0,
                "status": "error",
                "error": str(e)[:50],
                "last_access": ts,
            }})
    
    # Meta
    tool_set({"ns": PDBMAP_NS, "subs": ["_meta"], "value": {
        "scanned_at": ts,
        "namespaces": len(PDB_NAMESPACES),
        "total_entries": total_entries,
    }})
    
    return results

# ── Query ─────────────────────────────────────────────────────────

def map_get_namespace(ns):
    """Obtener info de un namespace."""
    _, tool_get, _ = _get_tools()
    r = tool_get({"ns": PDBMAP_NS, "subs": ["ns", ns]})
    return r.get("value") if r.get("success") else None

def map_report():
    """Reporte completo del mapa PDB."""
    _, tool_get, tool_order = _get_tools()
    results = []
    key = ""
    while True:
        r = tool_order({"ns": PDBMAP_NS, "subs": ["ns", key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        if key == "_meta": continue
        r2 = tool_get({"ns": PDBMAP_NS, "subs": ["ns", key]})
        if r2.get("success") and r2.get("value"):
            info = r2["value"]
            results.append({"ns": key, **info})
    return results

# ── CLI ──

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    
    if cmd == "scan":
        results = map_scan_all()
        print("🗺️  PDB Map — Namespaces:")
        for r in sorted(results, key=lambda x: x['entries'], reverse=True):
            icon = {"active": "🟢", "empty": "⏸️", "error": "🔴"}.get(r['status'], "❓")
            print(f"   {icon} {r['ns']:15s} {r['entries']:5d} entries  [{r['status']}]")
        total = sum(r['entries'] for r in results)
        print(f"\n   📊 Total: {len(results)} namespaces, {total} entries")
    
    elif cmd == "get":
        ns = sys.argv[2]
        info = map_get_namespace(ns)
        if info:
            print(f"  {ns}: {info['entries']} entries, {info['status']}")
        else:
            print(f"  {ns}: not found")
    
    elif cmd == "report":
        for r in map_report():
            print(f"  {r['ns']:15s} {r['entries']:5d} entries  [{r['status']}]")
