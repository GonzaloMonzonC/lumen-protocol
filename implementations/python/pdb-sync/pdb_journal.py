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
from pdb_tools import tool_set, tool_get, tool_order, tool_data, tool_kill

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

# ── A3: Recovery VERIFY mode (Zalo: 3 checks) ─────────────────────

def jrnl_verify_entry(change_data: dict) -> dict:
    """Zalo CHECK 1: Integridad estructural — validar que la entrada es JSON correcto."""
    required = ["op", "ns", "subs", "timestamp"]
    for field in required:
        if field not in change_data:
            return {"valid": False, "reason": f"missing field: {field}", "action": "skip"}
    if change_data["op"] not in ("SET", "KILL"):
        return {"valid": False, "reason": f"invalid op: {change_data['op']}", "action": "skip"}
    if not isinstance(change_data.get("subs"), list):
        return {"valid": False, "reason": "subs not a list", "action": "skip"}
    return {"valid": True, "action": "continue"}

def jrnl_verify_temporal(change_data: dict, checkpoint_ts: str) -> dict:
    """Zalo CHECK 2: timestamp debe ser posterior al checkpoint."""
    ts = change_data.get("timestamp", "")
    if ts <= checkpoint_ts:
        return {"valid": False, "reason": f"already applied (ts={ts[:19]} <= ckpt={checkpoint_ts[:19]})", "action": "skip"}
    return {"valid": True, "action": "continue"}

def jrnl_verify_precondition(change_data: dict) -> dict:
    """Zalo CHECK 3: valor actual en PDB debe coincidir con old_value."""
    ns = change_data.get("ns", "")
    subs = change_data.get("subs", [])
    old_val = change_data.get("old_value")
    op = change_data.get("op", "SET")

    current = tool_get({"ns": ns, "subs": subs})
    current_val = current.get("value") if current.get("success") else None

    if op == "SET":
        # Para SET, old_value debe coincidir con el valor actual (o ambos None)
        if old_val != current_val:
            return {"valid": False, "reason": f"conflict: old={old_val}, current={current_val}",
                    "action": "reject", "current": current_val}
    elif op == "KILL":
        # Para KILL, el nodo debe existir con old_value
        if current_val is None and old_val is not None:
            return {"valid": False, "reason": "node already deleted", "action": "skip"}
    return {"valid": True, "action": "apply"}

def jrnl_replay_entry(change_data: dict) -> dict:
    """Aplicar una entrada verificada a la PDB."""
    ns = change_data["ns"]
    subs = change_data["subs"]
    op = change_data["op"]

    if op == "SET":
        return tool_set({"ns": ns, "subs": subs, "value": change_data.get("new_value")})
    elif op == "KILL":
        return tool_kill({"ns": ns, "subs": subs})
    return {"success": False, "error": f"unknown op: {op}"}

def jrnl_recovery(file_seq: int = None, verify: bool = True, limit: int = 100):
    """DEJRNL recovery: aplicar cambios de un archivo de journal con VERIFY mode.
    
    Args:
        file_seq: archivo a recuperar (None = todos los pendientes)
        verify: activar VERIFY mode (3 checks de Zalo)
        limit: máximo de entradas a procesar
    
    Returns:
        {applied, skipped, rejected, conflicts, checkpoint}
    """
    from pdb_tools import tool_order as _order
    
    stats = {"applied": 0, "skipped": 0, "rejected": 0, "conflicts": [], "checkpoint": ""}
    ctrl = jrnl_control()
    checkpoint = ctrl.get("last_checkpoint", "") if ctrl else ""

    # Leer entradas de ^CHANGES desde el checkpoint
    key = ""
    processed = 0
    while processed < limit:
        r = tool_order({"ns": JOURNAL_NS, "subs": [key], "direction": 1})
        if not r.get("success") or not r.get("value"):
            break
        key = r["value"]
        if key in (CONTROL_KEY,):  # saltar nodos de control
            continue

        entry = tool_get({"ns": JOURNAL_NS, "subs": [key]})
        if not entry.get("success") or entry.get("value") is None:
            continue

        change = entry["value"]
        if isinstance(change, str):
            try: change = json.loads(change)
            except: continue

        # Zalo's 3 checks
        if verify:
            v1 = jrnl_verify_entry(change)
            if not v1["valid"]:
                stats["skipped"] += 1
                processed += 1
                continue

            v2 = jrnl_verify_temporal(change, checkpoint)
            if not v2["valid"]:
                stats["skipped"] += 1
                processed += 1
                continue

            v3 = jrnl_verify_precondition(change)
            if not v3["valid"]:
                if v3["action"] == "reject":
                    stats["rejected"] += 1
                    stats["conflicts"].append({"key": key, "reason": v3["reason"], "current": v3.get("current")})
                    # Guardar conflicto
                    tool_set({"ns": JOURNAL_NS, "subs": ["conflicts", key], "value": {
                        "change": change, "reason": v3["reason"], "current": v3.get("current")
                    }})
                else:
                    stats["skipped"] += 1
                processed += 1
                continue

        # Aplicar cambio
        result = jrnl_replay_entry(change)
        if result.get("success"):
            stats["applied"] += 1
            checkpoint = change.get("timestamp", checkpoint)
        else:
            stats["rejected"] += 1
        processed += 1

    # Actualizar checkpoint
    if stats["applied"] > 0 and checkpoint:
        stats["checkpoint"] = checkpoint
        if ctrl:
            ctrl["last_checkpoint"] = checkpoint
            tool_set({"ns": JOURNAL_NS, "subs": [CONTROL_KEY], "value": ctrl})

    return stats

# ── A4: Journal→DDP Bridge (Zalo: flag dirty + buffer destino + cron) ─

def jrnl_mark_dirty():
    """Marcar que hay cambios pendientes de sync."""
    tool_set({"ns": JOURNAL_NS, "subs": ["dirty"], "value": 1})

def jrnl_is_dirty() -> bool:
    """¿Hay cambios sin sincronizar?"""
    r = tool_get({"ns": JOURNAL_NS, "subs": ["dirty"]})
    return r.get("value") == 1 if r.get("success") else False

def jrnl_clear_dirty():
    """Limpiar flag dirty tras sync exitoso."""
    tool_set({"ns": JOURNAL_NS, "subs": ["dirty"], "value": 0})

def jrnl_buffer_push(destination: str, operation: dict):
    """Añadir operación al buffer de salida DDP.
    ^CHANGES("out",destino,seq) = operación
    """
    ctrl = jrnl_control()
    seq = ctrl.get("out_seq", 0) if ctrl else 0
    tool_set({"ns": JOURNAL_NS, "subs": ["out", destination, seq], "value": operation})
    if ctrl:
        ctrl["out_seq"] = seq + 1
        tool_set({"ns": JOURNAL_NS, "subs": [CONTROL_KEY], "value": ctrl})
    jrnl_mark_dirty()

def jrnl_buffer_flush(destination: str, limit: int = 50) -> list:
    """Vaciar buffer de salida para un destino. Devuelve operaciones pendientes."""
    ops = []
    seq = 0
    while len(ops) < limit:
        r = tool_get({"ns": JOURNAL_NS, "subs": ["out", destination, seq]})
        if not r.get("success") or r.get("value") is None:
            break
        ops.append({"seq": seq, "op": r["value"]})
        seq += 1
    return ops

def jrnl_sync_bridge():
    """Cron: si dirty=1, vaciar buffer y enviar al Edge.
    Integración con pdb-sync-bridge."""
    if not jrnl_is_dirty():
        return {"synced": 0, "status": "clean"}

    # Enviar buffer a pdb-edge-worker (simplificado para A4)
    synced = 0
    for dest in ["edge", "zalo", "lisa", "tom", "angi"]:
        ops = jrnl_buffer_flush(dest)
        if ops:
            synced += len(ops)
            # Limpiar buffer procesado
            for op in ops:
                tool_set({"ns": JOURNAL_NS, "subs": ["out", dest, op["seq"]], "value": None})

    if synced > 0:
        jrnl_clear_dirty()
    return {"synced": synced, "status": "synced" if synced > 0 else "empty"}

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
