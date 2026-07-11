#!/usr/bin/env python3
"""
pdb_journal.py — Control Block + métricas para ^CHANGES.

Sprint A1: Adapta el patrón de journaling MSM (JRNL + MAPJRNL) a PDB.
Añade métricas, status flags, y multi-file support a ^CHANGES.

Patrones MSM adaptados:
  - Control Block: jrnltab con SETs/KILLs/seq_no/blocks
  - Status flags: GOT_NEXT, AUTO_GEN, SUSPENDED, DAEMON, FORCE_EOF
  - Multi-file: ^SYS("JOURNAL",index)=file^status^type^size
  - Journal status: JSTAT display

Schema:
  ^CHANGES("control") = {
    status: "open" | "full" | "closed",
    seq_no: N,
    total_SETs: N,
    total_KILLs: N,
    full_writes: N,
    partial_writes: N,
    last_checkpoint: ISO8601,
    daemon_pid: N,
    flags: ["AUTO_GEN", "DAEMON_ACTIVE", ...]
  }

  ^CHANGES("file", seq) = {
    file: "changes_0001.jsonl",
    status: "E" | "O" | "F" | "C",
    type: "F" | "A",
    size_bytes: N,
    entries: N,
    created: ISO8601,
    closed: ISO8601
  }

Author: Hermes + CadencesLab (Sprint A1 — MSM→Lumen)
Date: 2026-07-11
"""

import json, os, sys
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
from pdb_tools import tool_set, tool_get, tool_order, tool_data

# ── Config ──────────────────────────────────────────────────────────

JOURNAL_NS = "CHANGES"
CONTROL_KEY = "control"
FILE_PREFIX = "file"

# ── Control Block ───────────────────────────────────────────────────

def jrnl_init():
    """Inicializar el control block del journal si no existe."""
    ctrl = tool_get({"ns": JOURNAL_NS, "subs": [CONTROL_KEY]})
    if not ctrl.get("success") or ctrl.get("value") is None:
        now = datetime.now(timezone.utc).isoformat()
        ctrl_data = {
            "status": "open",
            "seq_no": 0,
            "total_SETs": 0,
            "total_KILLs": 0,
            "full_writes": 0,
            "partial_writes": 0,
            "last_checkpoint": now,
            "created": now,
            "flags": ["AUTO_GEN"],
        }
        return tool_set({"ns": JOURNAL_NS, "subs": [CONTROL_KEY], "value": ctrl_data})
    return {"success": True, "already_exists": True}

def jrnl_control():
    """Leer el control block."""
    r = tool_get({"ns": JOURNAL_NS, "subs": [CONTROL_KEY]})
    return r.get("value") if r.get("success") else None

def jrnl_incr(op: str):
    """Incrementar contadores tras SET o KILL."""
    ctrl = jrnl_control()
    if not ctrl:
        jrnl_init()
        ctrl = jrnl_control()
        if not ctrl:
            return

    ctrl["seq_no"] = ctrl.get("seq_no", 0) + 1
    if op == "SET":
        ctrl["total_SETs"] = ctrl.get("total_SETs", 0) + 1
    elif op == "KILL":
        ctrl["total_KILLs"] = ctrl.get("total_KILLs", 0) + 1

    # Simular block writes (full=seq_no mod 10==0)
    if ctrl["seq_no"] % 10 == 0:
        ctrl["full_writes"] = ctrl.get("full_writes", 0) + 1
    else:
        ctrl["partial_writes"] = ctrl.get("partial_writes", 0) + 1

    ctrl["last_checkpoint"] = datetime.now(timezone.utc).isoformat()
    tool_set({"ns": JOURNAL_NS, "subs": [CONTROL_KEY], "value": ctrl})

def jrnl_set_flag(flag: str, enable: bool = True):
    """Activar/desactivar un flag del journal."""
    ctrl = jrnl_control()
    if not ctrl:
        return
    flags = set(ctrl.get("flags", []))
    if enable: flags.add(flag)
    else: flags.discard(flag)
    ctrl["flags"] = list(flags)
    tool_set({"ns": JOURNAL_NS, "subs": [CONTROL_KEY], "value": ctrl})

# ── Journal Status Display (JSTAT) ─────────────────────────────────

def jrnl_status():
    """JSTAT — mostrar estado del journal (como MAPJRNL de MSM)."""
    ctrl = jrnl_control()
    if not ctrl:
        return "Journal no inicializado"

    lines = []
    lines.append("═" * 50)
    lines.append("  📝 JOURNAL CONTROL BLOCK")
    lines.append("═" * 50)
    lines.append(f"  Status:       {ctrl.get('status', '?')}")
    lines.append(f"  Seq No:       {ctrl.get('seq_no', 0)}")
    lines.append(f"  Total SETs:   {ctrl.get('total_SETs', 0)}")
    lines.append(f"  Total KILLs:  {ctrl.get('total_KILLs', 0)}")
    lines.append(f"  Full writes:  {ctrl.get('full_writes', 0)}")
    lines.append(f"  Part writes:  {ctrl.get('partial_writes', 0)}")
    lines.append(f"  Checkpoint:   {ctrl.get('last_checkpoint', '?')[:19]}")
    flags = ctrl.get("flags", [])
    lines.append(f"  Flags:        {', '.join(flags) if flags else 'none'}")
    lines.append("═" * 50)

    # Multi-file info
    seq = 0
    while True:
        r = tool_get({"ns": JOURNAL_NS, "subs": [FILE_PREFIX, seq]})
        if not r.get("success") or r.get("value") is None:
            break
        f = r["value"]
        lines.append(f"  File {seq}: {f.get('file','?')} [{f.get('status','?')}] {f.get('entries',0)} entries, {f.get('size_bytes',0)} bytes")
        seq += 1

    return "\n".join(lines)

# ── Multi-file support ──────────────────────────────────────────────

# A2: Políticas de rotación (Lisa: entradas + tiempo, el que primero se cumpla)
MAX_ENTRIES_PER_FILE = 1000   # rotar cada 1000 entradas
MAX_HOURS_PER_FILE = 24       # rotar cada 24h

def jrnl_active_file():
    """Obtener el archivo de journal activo (status=O). Si no hay, crear uno."""
    ctrl = jrnl_control()
    if not ctrl:
        jrnl_init()
        ctrl = jrnl_control()
    seq = ctrl.get("active_file", -1)
    if seq >= 0:
        r = tool_get({"ns": JOURNAL_NS, "subs": [FILE_PREFIX, seq]})
        if r.get("success") and r.get("value") and r["value"].get("status") == "O":
            return {"seq": seq, "data": r["value"]}
    # No hay activo → crear uno
    return _create_active_file()

def _create_active_file():
    """Crear un nuevo archivo activo."""
    from datetime import datetime
    ctrl = jrnl_control()
    seq = ctrl.get("file_count", 0)
    now = datetime.now(timezone.utc)
    filename = f"changes_{now.strftime('%Y%m%d_%H%M%S')}.jsonl"
    file_data = {
        "file": filename, "status": "O", "type": "A",
        "size_bytes": 0, "entries": 0,
        "created": now.isoformat(), "closed": None,
        "first_seq_no": ctrl.get("seq_no", 0),
    }
    tool_set({"ns": JOURNAL_NS, "subs": [FILE_PREFIX, seq], "value": file_data})
    ctrl["active_file"] = seq
    ctrl["file_count"] = seq + 1
    tool_set({"ns": JOURNAL_NS, "subs": [CONTROL_KEY], "value": ctrl})
    return {"seq": seq, "data": file_data}

def jrnl_file_create(filename: str, file_type: str = "A"):
    """Crear un nuevo archivo de journal (como JRNL de MSM)."""
    ctrl = jrnl_control()
    if not ctrl:
        jrnl_init()
        ctrl = jrnl_control()
    seq = ctrl.get("seq_no", 0) // 1000  # nuevo archivo cada 1000 ops
    now = datetime.now(timezone.utc).isoformat()

    file_data = {
        "file": filename,
        "status": "O",       # Open
        "type": file_type,    # F=Fixed, A=Auto
        "size_bytes": 0,
        "entries": 0,
        "created": now,
        "closed": None,
    }
    tool_set({"ns": JOURNAL_NS, "subs": [FILE_PREFIX, seq], "value": file_data})
    return {"success": True, "seq": seq, "file": filename}

def jrnl_file_status(seq: int, new_status: str):
    """Cambiar status de archivo: E(empty), O(open), F(full), C(closed)."""
    r = tool_get({"ns": JOURNAL_NS, "subs": [FILE_PREFIX, seq]})
    if not r.get("success") or r.get("value") is None:
        return {"success": False, "error": "file not found"}
    f = r["value"]
    f["status"] = new_status
    if new_status == "C":
        f["closed"] = datetime.now(timezone.utc).isoformat()
    tool_set({"ns": JOURNAL_NS, "subs": [FILE_PREFIX, seq], "value": f})
    return {"success": True, "seq": seq, "status": new_status}

# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "init":
        print(jrnl_init())
    elif cmd == "status":
        print(jrnl_status())
    elif cmd == "incr":
        op = sys.argv[2] if len(sys.argv) > 2 else "SET"
        jrnl_incr(op)
        print(jrnl_status())
    elif cmd == "file":
        action = sys.argv[2] if len(sys.argv) > 2 else "create"
        if action == "create":
            name = sys.argv[3] if len(sys.argv) > 3 else f"changes_{datetime.now().strftime('%Y%m%d')}.jsonl"
            print(jrnl_file_create(name))
        elif action == "close":
            seq = int(sys.argv[3]) if len(sys.argv) > 3 else 0
            print(jrnl_file_status(seq, "C"))
    else:
        print(f"PDB Journal Control Block (Sprint A1 — MSM→Lumen)")
        print(f"  python pdb_journal.py init       # Inicializar journal")
        print(f"  python pdb_journal.py status     # Mostrar estado (JSTAT)")
        print(f"  python pdb_journal.py incr SET   # Incrementar contador SET")
        print(f"  python pdb_journal.py file create changes_001.jsonl  # Nuevo archivo")
