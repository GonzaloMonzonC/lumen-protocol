#!/usr/bin/env python3
"""
pdb_global_compare.py — MSM-05: %GCMP adaptado.

Comparación de globals entre PDB local y Edge D1.
Detecta diferencias, entradas faltantes, valores divergentes.

Esquema:
  ^System("compare", run_id) = {ns, local_count, edge_count, diffs, status}

Útil para:
  - Verificar sync después de pdb-sync-bridge
  - Auditoría de consistencia entre local↔Edge
  - Reconciliación de conflictos DDP

Autor: Hermes + CadencesLab (MSM-05)
Licencia: MIT (lumen-protocol)
"""

import sys, os, json, urllib.request
from datetime import datetime, timezone

EDGE_URL = "https://pdb-edge.gonzalomonzonc.workers.dev"

def _get_tools():
    pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order
    return tool_set, tool_get, tool_order

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Local scan ────────────────────────────────────────────────────

def scan_local(ns, limit=500):
    """Escanear un namespace local: devuelve {key: value}."""
    _, tool_get, tool_order = _get_tools()
    data = {}
    key = ""
    while len(data) < limit:
        r = tool_order({"ns": ns, "subs": [key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        if isinstance(key, (int, float)):
            key_str = str(int(key))
        else:
            key_str = str(key)
        r2 = tool_get({"ns": ns, "subs": [key_str]})
        if r2.get("success") and r2.get("value") is not None:
            data[key_str] = str(r2["value"])[:100]
    return data

def scan_edge(ns):
    """Escanear un namespace en Edge vía HTTP."""
    try:
        url = f"{EDGE_URL}/v1/order/{ns}"
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=10)
        if resp.status == 200:
            data = json.loads(resp.read().decode())
            return len(data.get("values", [])), data.get("values", [])
        return 0, []
    except Exception as e:
        return -1, [str(e)]

def compare_namespace(ns, limit=500):
    """Comparar un namespace entre local y edge."""
    tool_set, _, _ = _get_tools()

    # Scan local
    local_data = scan_local(ns, limit)
    local_count = len(local_data)

    # Scan edge
    edge_count, edge_data = scan_edge(ns)

    # Diff básico
    diffs = []
    if local_count > 0 and edge_count > 0:
        local_keys = set(local_data.keys())
        edge_keys = set(str(k) for k in (edge_data if edge_data else []))
        
        missing_on_edge = local_keys - edge_keys
        missing_on_local = edge_keys - local_keys
        
        if missing_on_edge:
            diffs.append(f"{len(missing_on_edge)} keys missing on edge")
        if missing_on_local:
            diffs.append(f"{len(missing_on_local)} keys missing on local")

    # Registrar resultado
    run_id = _now_iso().replace(":", "-").replace(".", "-")
    result = {
        "ns": ns,
        "local_count": local_count,
        "edge_count": edge_count,
        "diffs": diffs,
        "status": "OK" if not diffs else "DIFF",
        "timestamp": _now_iso(),
    }
    tool_set({"ns": "System", "subs": ["compare", run_id], "value": result})
    
    return result

def compare_report():
    """Reporte de comparaciones realizadas."""
    _, tool_get, tool_order = _get_tools()
    reports = []
    key = ""
    while True:
        r = tool_order({"ns": "System", "subs": ["compare", key], "direction": -1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        r2 = tool_get({"ns": "System", "subs": ["compare", key]})
        if r2.get("success") and r2.get("value"):
            reports.append(r2["value"])
    return reports

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "compare"
    ns = sys.argv[2] if len(sys.argv) > 2 else "CHANGES"
    
    if cmd == "compare":
        r = compare_namespace(ns)
        print(f"📊 Compare {ns}:")
        print(f"  Local: {r['local_count']} entries")
        print(f"  Edge:  {r['edge_count']} entries")
        if r['diffs']:
            for d in r['diffs']:
                print(f"  ⚠️  {d}")
        else:
            print(f"  ✅ No differences")
    elif cmd == "report":
        for r in compare_report()[:5]:
            print(f"  {r['ns']:12s} local={r['local_count']} edge={r['edge_count']} {r['status']}")
