#!/usr/bin/env python3
"""
pdb-journal — Control Block del journaling, inspirado en MSM MAPJRNL.

Añade a ^CHANGES un control block con:
- METRICAS: SETs count, KILLs count, seq_no, full_block_writes, partial_writes
- STATUS: flags MSM (GOT_NEXT, AUTO_GEN, SUSPENDED, DAEMON, SHUTDOWN)
- TIMESTAMP: created_at, last_activity

Schema:
    ^CHANGES("control") = {
        "sets": 0, "kills": 0, "seq_no": 0,
        "full_writes": 0, "partial_writes": 0,
        "status": 0,
        "created_at": "2026-07-11T...",
        "last_write_at": "2026-07-11T..."
    }

    ^CHANGES("metrics") = {
        "total_ops": 0, "healthy": True,
        "last_seq": 0
    }

Flags (como MAPJRNL jflag):
    #1  = GOT_NEXT_JRNL
    #2  = AUTO_GEN_JRNL
    #4  = JRNL_SUSPENDED
    #8  = JRNL_DAEMON
    #10 = JRNL_SHUTDOWN
    #20 = FORCE_JRNL_EOF

Integración: llamar a journal_record_operation() desde tool_set/tool_kill.

Autor: Hermes + CadencesLab (A1 — Sprint A MSM→Lumen)
Licencia: MIT (lumen-protocol)
"""

import os, sys, time, json
from datetime import datetime, timezone

# ── Config ──────────────────────────────────────────────────────────

CHANGES_NS = "CHANGES"

# MAPJRNL-style flags (bitfield)
JFLAG_GOT_NEXT    = 1 << 0  # #1
JFLAG_AUTO_GEN    = 1 << 1  # #2
JFLAG_SUSPENDED   = 1 << 2  # #4
JFLAG_DAEMON      = 1 << 3  # #8
JFLAG_SHUTDOWN    = 1 << 4  # #10
JFLAG_FORCE_EOF   = 1 << 5  # #20

JFLAG_NAMES = {
    JFLAG_GOT_NEXT:  "GOT_NEXT_JRNL",
    JFLAG_AUTO_GEN:  "AUTO_GEN_JRNL",
    JFLAG_SUSPENDED: "JRNL_SUSPENDED",
    JFLAG_DAEMON:    "JRNL_DAEMON",
    JFLAG_SHUTDOWN:  "JRNL_SHUTDOWN",
    JFLAG_FORCE_EOF: "FORCE_JRNL_EOF",
}

# ── Helpers ─────────────────────────────────────────────────────────

def _get_tools():
    pdb_dir = os.path.expanduser(
        "~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"
    )
    if pdb_dir not in sys.path:
        sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get
    return tool_set, tool_get

def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Control Block ────────────────────────────────────────────────────

def journal_init():
    """Inicializar el control block si no existe."""
    tool_set, tool_get = _get_tools()

    ctrl = tool_get({"ns": CHANGES_NS, "subs": ["control"]})
    if not ctrl.get("found") and not ctrl.get("value"):
        ctrl_block = {
            "sets": 0,
            "kills": 0,
            "seq_no": 0,
            "full_writes": 0,
            "partial_writes": 0,
            "status": 0,
            "created_at": _now(),
            "last_write_at": _now(),
        }
        tool_set({"ns": CHANGES_NS, "subs": ["control"], "value": ctrl_block})
        return ctrl_block
    return ctrl.get("value")

def journal_get_control():
    """Leer control block actual."""
    _, tool_get = _get_tools()
    ctrl = tool_get({"ns": CHANGES_NS, "subs": ["control"]})
    return ctrl.get("value") if ctrl.get("value") else journal_init()

def journal_set_flag(flag):
    """Activar un flag MSM-style (bitwise OR)."""
    tool_set, _ = _get_tools()
    ctrl = journal_get_control()
    if ctrl:
        ctrl["status"] = ctrl.get("status", 0) | flag
        tool_set({"ns": CHANGES_NS, "subs": ["control"], "value": ctrl})

def journal_clear_flag(flag):
    """Desactivar un flag (bitwise AND NOT)."""
    tool_set, _ = _get_tools()
    ctrl = journal_get_control()
    if ctrl:
        ctrl["status"] = ctrl.get("status", 0) & ~flag
        tool_set({"ns": CHANGES_NS, "subs": ["control"], "value": ctrl})

def journal_has_flag(flag):
    """Verificar si un flag está activo."""
    ctrl = journal_get_control()
    return bool(ctrl.get("status", 0) & flag) if ctrl else False

def journal_record_operation(op: str, ns: str, is_full_write: bool = True):
    """Registrar una operación en el control block (SET o KILL).
    Llamar desde tool_set (op='SET') y tool_kill (op='KILL').

    Args:
        op: 'SET' | 'KILL'
        ns: namespace de la operación (e.g. 'System', 'CHANGES')
        is_full_write: True = full block write, False = partial
    """
    # No registrar cambios en el propio CHANGES (evitar recursión)
    if ns == CHANGES_NS:
        return

    tool_set, _ = _get_tools()
    ctrl = journal_get_control()
    if not ctrl:
        ctrl = journal_init()

    if op == "SET":
        ctrl["sets"] = ctrl.get("sets", 0) + 1
    elif op == "KILL":
        ctrl["kills"] = ctrl.get("kills", 0) + 1

    if is_full_write:
        ctrl["full_writes"] = ctrl.get("full_writes", 0) + 1
    else:
        ctrl["partial_writes"] = ctrl.get("partial_writes", 0) + 1

    ctrl["seq_no"] = ctrl.get("seq_no", 0) + 1
    ctrl["last_write_at"] = _now()

    tool_set({"ns": CHANGES_NS, "subs": ["control"], "value": ctrl})

def journal_get_metrics():
    """Obtener métricas de salud del journal."""
    ctrl = journal_get_control()
    if not ctrl:
        return {}

    sets = ctrl.get("sets", 0)
    kills = ctrl.get("kills", 0)
    total = sets + kills
    full = ctrl.get("full_writes", 0)
    partial = ctrl.get("partial_writes", 0)
    total_writes = full + partial

    metrics = {
        "total_ops": total,
        "sets": sets,
        "kills": kills,
        "ratio_set_kill": round(sets / max(kills, 1), 2),
        "full_writes": full,
        "partial_writes": partial,
        "write_efficiency": round(full / max(total_writes, 1) * 100, 1),
        "seq_no": ctrl.get("seq_no", 0),
        "status": ctrl.get("status", 0),
        "flags": [name for bit, name in JFLAG_NAMES.items()
                  if ctrl.get("status", 0) & bit],
        "healthy": ctrl.get("status", 0) == 0,
        "created_at": ctrl.get("created_at", ""),
        "last_write_at": ctrl.get("last_write_at", ""),
    }
    return metrics

# ── Status display (como MAPJRNL pero legible) ─────────────────────

def journal_status():
    """Mostrar estado del control block (como MAPJRNL)."""
    metrics = journal_get_metrics()
    if not metrics:
        return "No journal control block found."

    lines = [
        "╔══════════════════════════════════════╗",
        "║   JOURNAL CONTROL BLOCK (MAPJRNL)   ║",
        "╚══════════════════════════════════════╝",
        f"   SETs:       {metrics['sets']:>8}",
        f"   KILLs:      {metrics['kills']:>8}",
        f"   Ratio S/K:  {metrics['ratio_set_kill']:>8.2f}",
        f"   seq_no:     {metrics['seq_no']:>8}",
        f"   Full writes:{metrics['full_writes']:>8}",
        f"   Part writes:{metrics['partial_writes']:>8}",
        f"   Write eff:  {metrics['write_efficiency']:>7.1f}%",
        f"   Status:     {metrics['status']:>8}  {metrics['flags']}",
        f"   Healthy:    {str(metrics['healthy']):>8}",
        f"   Created:    {metrics['created_at']}",
        f"   Last write: {metrics['last_write_at']}",
    ]
    return "\n".join(lines)

# ── CLI ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "init":
        result = journal_init()
        print(f"Control block initialized: {result}")

    elif cmd == "record":
        op = sys.argv[2] if len(sys.argv) > 2 else "SET"
        ns = sys.argv[3] if len(sys.argv) > 3 else "test"
        journal_record_operation(op, ns)
        print(f"Recorded {op} on {ns}")

    elif cmd == "status":
        print(journal_status())

    elif cmd == "metrics":
        import json
        print(json.dumps(journal_get_metrics(), indent=2))

    elif cmd == "set-flag":
        flag_name = sys.argv[2] if len(sys.argv) > 2 else "GOT_NEXT"
        flag_map = {v: k for k, v in JFLAG_NAMES.items()}
        if flag_name in flag_map:
            journal_set_flag(flag_map[flag_name])
            print(f"Flag {flag_name} set")
        else:
            print(f"Unknown flag: {flag_name}")
            print(f"Available: {list(flag_map.keys())}")

    else:
        print("Uso: python pdb_journal.py [init|record|status|metrics|set-flag]")
