#!/usr/bin/env python3
"""
pdb_type.py — MSM-09: TTEST — Type testing de nodos.

Inspirado en MSM B-tree opcode 't' (case 0x74 en FUN_48c010).
Determina tipo de nodo: hoja, interno, puntero, o 0/1/10/11 ($DATA).

MSM: buffer type field → lookup array → type name.
PDB: tool_type(ns, subs) → {data_type, node_type, details}

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, json, sqlite3
import _paths  # rutas repo-relativas

def _get_tools():
    pdb_dir = _paths.PDB_DIR_S
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_get, tool_order, tool_data, tool_set
    return tool_get, tool_order, tool_data, tool_set

def _get_db():
    """Conectar a PDB SQLite directamente para info de nodo."""
    from pdb_tools import pdb_connect
    return pdb_connect()

def node_type(ns, subs):
    """Determinar tipo de nodo (TTEST).
    
    Returns:
        data_type: 0=no existe, 1=valor, 10=hijos, 11=ambos
        has_value: bool
        has_children: bool
        children_count: int (aprox)
        size_bytes: int (tamaño del valor)
        first_child: str
    """
    tg, to, td, ts = _get_tools()
    
    # $DATA
    r = td({"ns": ns, "subs": subs})
    dt = r.get("value", 0) if r.get("success") else 0
    
    result = {
        "ns": ns,
        "subs": subs,
        "data_type": dt,
        "has_value": dt in (1, 11),
        "has_children": dt in (10, 11),
    }
    
    # Value
    if dt in (1, 11):
        r2 = tg({"ns": ns, "subs": subs})
        val = r2.get("value") if r2.get("success") else None
        result["value"] = val
        result["size_bytes"] = len(str(val)) if val else 0
    
    # Children count
    if dt in (10, 11):
        count, first = _count_children(ns, subs)
        result["children_count"] = count
        result["first_child"] = first
    else:
        result["children_count"] = 0
        result["first_child"] = None
    
    return result

def _count_children(ns, subs, limit=1000):
    """Contar hijos de un nodo (MSM: B-tree internal node traversal)."""
    tg, to, td, ts = _get_tools()
    count = 0
    first = None
    key = ""
    while True:
        r = to({"ns": ns, "subs": subs + [key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        if first is None: first = key
        count += 1
        if count >= limit: break
    return count, first

def tool_type(ns, subs):
    """TTEST wrapper — info completa del nodo."""
    return node_type(ns, subs)

def node_summary(ns, subs):
    """Resumen legible del nodo (como MSM TYPE display)."""
    n = node_type(ns, subs)
    
    type_labels = {
        0: "NONE — No existe",
        1: "LEAF — Tiene valor, sin hijos",
        10: "NODE — Sin valor, con hijos",
        11: "FULL — Valor + hijos",
    }
    
    lines = [f"  ^{ns}({','.join(str(s) for s in subs)})"]
    lines.append(f"  Type: {type_labels.get(n['data_type'], '?')}")
    if n.get("value") is not None:
        lines.append(f"  Value: {str(n['value'])[:80]}")
    if n.get("children_count"):
        lines.append(f"  Children: {n['children_count']} (first: {n['first_child']})")
    if n.get("size_bytes"):
        lines.append(f"  Size: {n['size_bytes']} bytes")
    
    return "\n".join(lines)

# ── CLI ──

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "demo"
    
    if cmd == "demo":
        print("📋 PDB TTEST — Node Type Testing\n")
        
        for ns, subs in [("System", ["config"]), ("System", ["help"]),
                         ("ROUTINE", ["INDEX", "MSERVER"]), ("NONEXISTENT", [])]:
            print(node_summary(ns, subs))
            print()
    
    elif cmd == "type":
        ns = sys.argv[2]
        subs = sys.argv[3].split(",") if len(sys.argv) > 3 else []
        import json
        print(json.dumps(node_type(ns, subs), indent=2))
