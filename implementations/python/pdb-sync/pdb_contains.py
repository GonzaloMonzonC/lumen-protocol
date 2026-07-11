#!/usr/bin/env python3
"""
pdb_contains.py — MSM-10: CONTAINS — Búsqueda por patrón en B-tree.

Inspirado en MSM opcode '[' (0x5b) = set pattern, ']' (0x5d) = filter control.

MSM: strncpy(pattern) + flag|=2 → iteraciones filtradas por patrón.
PDB: tool_contains(ns, subs, pattern, limit=100) → [(key, value), ...]

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, fnmatch, re

def _get_tools():
    pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_get, tool_order, tool_data
    return tool_get, tool_order, tool_data

# ── Pattern matching engine ─────────────────────────────────────

def _match_pattern(key, pattern):
    """Match key against pattern.
    
    Soporta:
    - Wildcard: * = cualquier texto, ? = un carácter
    - Literal: "texto" coincide exactamente
    - Prefijo: "pre*" coincide con keys que empiezan por "pre"
    """
    if not pattern:
        return True
    return fnmatch.fnmatch(str(key), pattern)

# ── CONTAINS API ────────────────────────────────────────────────

def tool_contains(ns, subs, pattern, limit=100, direction=1):
    """Buscar subíndices que coincidan con un patrón.
    
    MSM: '[' opcode → set pattern buffer + flag |= 2.
    PDB: pdb_contains(ns, subs, pattern) → [(key, value), ...]
    
    Args:
        ns: Namespace
        subs: Subíndices base
        pattern: Glob pattern (*, ?, [chars])
        limit: Max resultados
        direction: 1=forward, -1=backward
    
    Returns:
        Lista de (key, value) que coinciden
    """
    tg, to, td = _get_tools()
    results = []
    
    # Flag |= 2 — modo pattern (MSM: set pattern buffer)
    key = ""
    while len(results) < limit:
        r = to({"ns": ns, "subs": subs + [key], "direction": direction})
        if not r.get("success") or r.get("value") is None:
            break
        key = r["value"]
        
        if _match_pattern(key, pattern):
            r2 = tg({"ns": ns, "subs": subs + [key]})
            val = r2.get("value") if r2.get("success") else None
            results.append((key, val))
    
    return results

def tool_contains_values(ns, subs, pattern, limit=100):
    """Buscar valores que contengan texto.
    
    Útil para búsqueda full-text sobre subíndices.
    """
    tg, to, td = _get_tools()
    results = []
    
    key = ""
    while len(results) < limit:
        r = to({"ns": ns, "subs": subs + [key], "direction": 1})
        if not r.get("success") or r.get("value") is None:
            break
        key = r["value"]
        
        r2 = tg({"ns": ns, "subs": subs + [key]})
        val = r2.get("value") if r2.get("success") else ""
        if pattern.lower() in str(val).lower():
            results.append((key, val))
    
    return results

def tool_contains_first(ns, subs, pattern):
    """Primer resultado que coincida (más rápido, sin limit)."""
    results = tool_contains(ns, subs, pattern, limit=1)
    return results[0] if results else None

# ── CLI ──

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "demo"
    
    if cmd == "demo":
        print("📋 PDB CONTAINS — Pattern search in B-tree\n")
        
        # Buscar en System todo lo que empiece por "d"
        results = tool_contains("System", [], "d*", limit=10)
        print(f"  ^System(\"d*\") → {len(results)} matches:")
        for k, v in results[:5]:
            print(f"    {k} = {str(v)[:50]}")
        
        print()
        
        # Buscar en System todo lo que contenga "config"
        results2 = tool_contains("System", [], "*conf*", limit=10)
        print(f"  ^System(\"*conf*\") → {len(results2)} matches:")
        for k, v in results2[:5]:
            print(f"    {k} = {str(v)[:50]}")
        
        print()
        
        # Buscar por patrón exacto
        r = tool_contains_first("System", [], "decisions")
        if r:
            print(f"  ^System(\"decisions\") → {r}")
    
    elif cmd == "search":
        ns = sys.argv[2]
        pattern = sys.argv[3] if len(sys.argv) > 3 else "*"
        limit = int(sys.argv[4]) if len(sys.argv) > 4 else 20
        results = tool_contains(ns, [], pattern, limit)
        print(f"📋 {len(results)} matches in ^{ns}(\"{pattern}\"):")
        for k, v in results:
            print(f"  {k} = {str(v)[:60]}")
