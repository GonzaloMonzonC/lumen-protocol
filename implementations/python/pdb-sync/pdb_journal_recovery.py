#!/usr/bin/env python3
"""
pdb_journal_recovery.py — Recovery DEJRNL con VERIFY mode (A3).

Basado en el DEJRNL de MSM y los 3 checks de Zalo:
1. INTEGRIDAD ESTRUCTURAL — old_value/new_value JSON válido
2. CONSISTENCIA TEMPORAL — timestamp > último checkpoint  
3. PRECONDICIÓN DE ESTADO — PDB actual == old_value

Si pasa los 3 → APPLY (aplica new_value)
Check 1 falla → CORRUPT (salta, registra en ^CHANGES("corrupt"))
Check 2 falla → REDUNDANT (ignora, ya aplicada)
Check 3 falla → CONFLICT (rechaza, registra en ^CHANGES("conflicts"))

Inspired by: DEJRNL (145 líneas) + DEJRNL1-3 (319 líneas), MSM

Author: Hermes + CadencesLab (A3 — Sprint A MSM→Lumen)
License: MIT (lumen-protocol)
"""

import os, sys, json
from datetime import datetime, timezone

# ── Config ──────────────────────────────────────────────────────────

CHANGES_NS = "CHANGES"

# ── Helpers ─────────────────────────────────────────────────────────

def _get_tools():
    pdb_dir = os.path.expanduser(
        "~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"
    )
    if pdb_dir not in sys.path:
        sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order, tool_kill
    return tool_set, tool_get, tool_order, tool_kill

def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Checkpoint ─────────────────────────────────────────────────────

CHECKPOINT_FILE = os.path.expanduser("~/.hermes/pdb-recovery-checkpoint.json")

def _load_checkpoint():
    """Cargar el checkpoint de recovery."""
    try:
        with open(CHECKPOINT_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_ts": 0, "last_seq": 0, "applied": 0}

def _save_checkpoint(cp):
    """Guardar checkpoint."""
    os.makedirs(os.path.dirname(CHECKPOINT_FILE), exist_ok=True)
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(cp, f)

# ── VERIFY checks (Zalo) ────────────────────────────────────────────

def check_integrity(entry):
    """Check 1: old_value y new_value deben ser JSON válidos."""
    for key in ("old_value", "new_value"):
        val = entry.get(key)
        if val is not None and not isinstance(val, (dict, list, str, int, float, bool)):
            return False, f"invalid type for {key}: {type(val).__name__}"
    return True, None

def check_timestamp(entry, checkpoint):
    """Check 2: timestamp debe ser posterior al último checkpoint."""
    ts = entry.get("timestamp_ns", 0)
    last_ts = checkpoint.get("last_ts", 0)
    if ts <= last_ts:
        return False, f"ts {ts} <= checkpoint {last_ts}"
    return True, None

def check_precondition(entry, tool_get, pdb_value):
    """Check 3: valor actual en PDB debe coincidir con old_value."""
    old = entry.get("old_value")
    op = entry.get("op")

    # KILL: no check de precondición (no old_value relevante)
    if op == "KILL":
        return True, None

    # SET: valor actual debe == old_value
    if pdb_value != old:
        return False, f"PDB has {pdb_value!r}, expected {old!r}"
    return True, None

# ── Recovery engine ────────────────────────────────────────────────

def recovery_apply(entries, dry_run=False):
    """Aplicar un lote de entradas del journal con VERIFY mode.

    Args:
        entries: lista de dicts de ^CHANGES
        dry_run: True = solo verificar, no aplicar

    Returns:
        dict con resultados
    """
    pdb_dir = os.path.expanduser(
        "~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"
    )
    if pdb_dir not in sys.path:
        sys.path.insert(0, pdb_dir)
    import pdb_tools
    tool_set = pdb_tools.tool_set
    tool_get = pdb_tools.tool_get
    tool_kill = pdb_tools.tool_kill

    cp = _load_checkpoint()

    stats = {"applied": 0, "corrupt": 0, "redundant": 0, "conflict": 0, "total": len(entries)}

    for i, entry in enumerate(entries):
        # Check 1: Integridad estructural
        ok, reason = check_integrity(entry)
        if not ok:
            stats["corrupt"] += 1
            if not dry_run:
                tool_set({"ns": CHANGES_NS, "subs": ["corrupt", i], "value": {
                    "entry": entry, "reason": reason, "at": _now()
                }})
            continue

        # Check 2: Consistencia temporal
        ok, reason = check_timestamp(entry, cp)
        if not ok:
            stats["redundant"] += 1
            continue

        # Check 3: Precondición de estado
        ns = entry.get("ns")
        subs = entry.get("subs", [])
        op = entry.get("op")

        current = None
        if op == "SET":
            r = tool_get({"ns": ns, "subs": subs})
            if r.get("success"):
                current = r.get("value")

        ok, reason = check_precondition(entry, tool_get, current)
        if not ok:
            stats["conflict"] += 1
            if not dry_run:
                tool_set({"ns": CHANGES_NS, "subs": ["conflicts", i], "value": {
                    "entry": entry, "current": current, "reason": reason, "at": _now()
                }})
            continue

        # ✅ Pasa los 3 checks → APPLY
        if not dry_run and op in ("SET", "KILL", "MERGE"):
            new_val = entry.get("new_value")
            if op == "SET":
                tool_set({"ns": ns, "subs": subs, "value": new_val})
            elif op == "KILL":
                tool_kill({"ns": ns, "subs": subs})
            elif op == "MERGE":
                pass  # TODO: merge rebuild

        stats["applied"] += 1
        cp["last_ts"] = entry.get("timestamp_ns", cp["last_ts"])
        cp["last_seq"] = stats["applied"]
        _save_checkpoint(cp)

    stats["checkpoint"] = cp
    return stats

def recovery_from_changes(limit=1000, dry_run=False):
    """Recuperar desde ^CHANGES usando VERIFY mode y SQL directo."""
    import sys, os
    pdb_dir = os.path.expanduser(
        "~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"
    )
    if pdb_dir not in sys.path:
        sys.path.insert(0, pdb_dir)
    import pdb_tools
    import json

    cp = _load_checkpoint()

    # Leer via SQL para evitar problemas de precisión float
    tool_query = pdb_tools.tool_query
    r = tool_query({"sql": "SELECT value FROM _globals WHERE ns='CHANGES' ORDER BY rowid ASC LIMIT ?", "params": [limit]})

    if not r.get("success") or not r.get("rows"):
        return {"applied": 0, "total": 0, "msg": "No entries", "checkpoint": cp}

    entries = []
    for row in r["rows"]:
        raw_val = row.get("value")
        if not raw_val:
            continue
        try:
            entry = json.loads(raw_val) if isinstance(raw_val, str) else raw_val
            if isinstance(entry, str):
                entry = json.loads(entry)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and "op" in entry:
            entries.append(entry)

    if not entries:
        return {"applied": 0, "total": 0, "msg": "No valid entries", "checkpoint": cp}

    return recovery_apply(entries, dry_run=dry_run)

    if not entries:
        return {"applied": 0, "total": 0, "msg": "No new entries", "checkpoint": cp}

    return recovery_apply(entries, dry_run=dry_run)

# ── CLI ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    dry_run = "--dry-run" in sys.argv
    verbose = "-v" in sys.argv or "--verbose" in sys.argv

    if cmd == "verify":
        result = recovery_from_changes(limit=100, dry_run=dry_run)
        print(f"✅ Applied: {result['applied']}")
        print(f"❌ Corrupt: {result.get('corrupt', 0)}")
        print(f"⏭️  Redundant: {result.get('redundant', 0)}")
        print(f"⚔️  Conflicts: {result.get('conflict', 0)}")
        print(f"📊 Total: {result.get('total', 0)}")
        if verbose:
            import json
            print(json.dumps(result.get("checkpoint", {}), indent=2))

    elif cmd == "status":
        cp = _load_checkpoint()
        print(f"📊 Recovery checkpoint:")
        print(f"  Last ts:    {cp.get('last_ts', 0)}")
        print(f"  Last seq:   {cp.get('last_seq', 0)}")
        print(f"  Applied:    {cp.get('applied', 0)}")

    elif cmd == "reset":
        _save_checkpoint({"last_ts": 0, "last_seq": 0, "applied": 0})
        print("Checkpoint reset.")

    else:
        print("Uso: python pdb_journal_recovery.py [verify|status|reset] [--dry-run] [-v]")
