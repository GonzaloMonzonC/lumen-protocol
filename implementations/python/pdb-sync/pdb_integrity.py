#!/usr/bin/env python3
"""
pdb_integrity.py — MSMINTEG: PDB Integrity Checker.

Basado en MSMINTEG (556 líneas) de MSM.
Verifica integridad de ^ROUTINE con SHA256 + detecta orphans.

Zalo: "Si hay corrupción detectable, mejor tenerlo."

Uso:
  python pdb_integrity.py check    → full check
  python pdb_integrity.py routines → solo routines
  python pdb_integrity.py orphans  → solo orphans

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, hashlib, json
import _paths  # rutas repo-relativas
from datetime import datetime, timezone

def _get_tools():
    pdb_dir = _paths.PDB_DIR_S
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_get, tool_order, tool_set
    return tool_get, tool_order, tool_set

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Checksum ──

def _sha256(text):
    if isinstance(text, bytes): return hashlib.sha256(text).hexdigest()
    return hashlib.sha256(text.encode()).hexdigest()

def _get_routine_names():
    """Obtener nombres de todas las rutinas cargadas."""
    tg, to, ts = _get_tools()
    names = []
    idx_key = ""
    while True:
        r = to({"ns": "ROUTINE", "subs": ["INDEX", idx_key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        idx_key = r["value"]
        names.append(idx_key)
    return names

def _get_routine_code(name):
    """Obtener código completo de una rutina."""
    tg, to, _ = _get_tools()
    lines = []
    key = ""
    while True:
        r = to({"ns": "ROUTINE", "subs": [name, key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        r2 = tg({"ns": "ROUTINE", "subs": [name, key]})
        if r2.get("success") and r2.get("value"):
            lines.append(str(r2["value"]))
    return "\n".join(lines)

# ── Stored checksums ──

def _stored_checksums():
    """Obtener checksums almacenados."""
    tg, to, _ = _get_tools()
    sums = {}
    key = ""
    while True:
        r = to({"ns": "ROUTINE", "subs": ["_checksum", key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        r2 = tg({"ns": "ROUTINE", "subs": ["_checksum", key]})
        if r2.get("success") and r2.get("value"):
            sums[key] = r2["value"]
    return sums

def _store_checksum(name, checksum):
    """Almacenar checksum."""
    _, _, ts = _get_tools()
    ts({"ns": "ROUTINE", "subs": ["_checksum", name], "value": checksum})

# ── Integrity checks ──

def integrity_check_routines():
    """Verificar checksum SHA256 de cada rutina.
    
    Como MSMINTEG: $ZCRC vs stored value.
    Nosotros: SHA256 vs stored.
    """
    names = _get_routine_names()
    stored = _stored_checksums()
    results = {"ok": [], "mismatch": [], "new": [], "missing": []}
    
    for name in names:
        code = _get_routine_code(name)
        actual = _sha256(code)
        
        if name in stored:
            if stored[name] == actual:
                results["ok"].append(name)
            else:
                results["mismatch"].append({"name": name, "expected": stored[name], "actual": actual})
        else:
            results["new"].append(name)
            _store_checksum(name, actual)
    
    # Routines in stored but not in INDEX
    for name in stored:
        if name not in names:
            results["missing"].append(name)
    
    return results

def integrity_check_orphans():
    """Detectar namespaces huérfanos (sin rutina asociada)."""
    tg, to, _ = _get_tools()
    KNOWN_NAMESPACES = [
        "System", "CHANGES", "ROUTINE", "DDP", "Agent", "LOGON",
        "MSAJOB", "MSASYS", "RTHIST", "CSFMON", "PDBMAP",
        "TEST", "STRESS", "CLIMA", "COMPARE_TEST", "PROCESSES",
        "BIJ", "MSERVER", 
    ]
    orphans = []
    for ns in KNOWN_NAMESPACES:
        # Si el namespace existe en PDB (tiene al menos una entrada)
        r = to({"ns": ns, "subs": [""], "direction": 1})
        has_data = r.get("success") and r.get("value") is not None
        
        # Y no tiene rutina asociada
        r2 = tg({"ns": "ROUTINE", "subs": ["INDEX", ns]})
        has_routine = r2.get("success") and r2.get("value") is not None
        
        if has_data and not has_routine:
            orphans.append(ns)
    
    return orphans

def integrity_check_all():
    """Ejecutar todos los checks (MSMINTEG full)."""
    ts = _now_iso()
    
    routines = integrity_check_routines()
    orphans = integrity_check_orphans()
    
    # Reportar a ^System("errors") si hay problemas
    _, _, ts_set = _get_tools()
    for mismatch in routines.get("mismatch", []):
        ts_set({"ns": "System", "subs": ["errors", "integrity", ts], "value": {
            "type": "checksum_mismatch",
            "routine": mismatch["name"],
            "severity": "warning",
        }})
    for orphan in orphans:
        ts_set({"ns": "System", "subs": ["errors", "integrity", ts], "value": {
            "type": "orphan_namespace",
            "namespace": orphan,
            "severity": "info",
        }})
    
    return {
        "timestamp": ts,
        "routines": {
            "total_ok": len(routines["ok"]),
            "mismatches": len(routines["mismatch"]),
            "new_checksums": len(routines["new"]),
            "missing_from_index": len(routines["missing"]),
            "details": routines,
        },
        "orphans": {
            "total": len(orphans),
            "namespaces": orphans,
        },
        "healthy": len(routines["mismatch"]) == 0,
    }

# ── CLI ──

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    
    if cmd == "check":
        r = integrity_check_all()
        print(f"📋 PDB Integrity Check @ {r['timestamp']}")
        print(f"\n📦 ROUTINES:")
        print(f"   ✅ {r['routines']['total_ok']} OK")
        print(f"   ❌ {r['routines']['mismatches']} mismatches")
        print(f"   🆕 {r['routines']['new_checksums']} new checksums")
        print(f"\n👻 ORPHANS:")
        o_count = r['orphans']['total']
        print(f"   {'✅ None' if not o_count else '⚠️  ' + str(o_count)}")
        for o in r['orphans']['namespaces']:
            print(f"   👻 {o}")
        print(f"\n{'✅ INTEGRITY: PASS' if r['healthy'] else '❌ INTEGRITY: FAIL'}")
    
    elif cmd == "routines":
        r = integrity_check_routines()
        for name in r["ok"][:10]:
            print(f"  ✅ {name}")
        if r["mismatch"]:
            for m in r["mismatch"]:
                print(f"  ❌ {m['name']}: expected {m['expected'][:16]}... got {m['actual'][:16]}...")
        if r["new"]:
            print(f"  🆕 {len(r['new'])} new checksums stored")
    
    elif cmd == "orphans":
        o = integrity_check_orphans()
        print(f"👻 Orphans: {len(o)}")
        for ns in o:
            print(f"  {ns}")
