#!/usr/bin/env python3
"""
pdb_bij.py — BIJ: Before-Image Journal (rollback transaccional).

Basado en BIJ (163 líneas) + BIJ1 (145) + BIJFMT (161) de MSM.

CONCEPTO MSM: Antes de modificar un dato, guardar el VALOR ANTERIOR
en un journal separado. Si la transacción falla, restaurar desde BIJ.

Diferencia con ^CHANGES:
  ^CHANGES = AFTER image (registra tras la modificación) → forward recovery
  ^BIJ     = BEFORE image (registra antes de la modificación) → backward recovery

NECESITAMOS AMBOS para integridad transaccional completa.

Flujo:
  tool_set/tool_kill → _record_change (^CHANGES) → _record_bij (^BIJ)
     → Si falla: bij_rollback() restaura estado anterior

Esquema:
  ^BIJ("file", seq) = {tx_id, ns, subs, old_value, timestamp, status}
  ^BIJ("tx", tx_id) = [entry1, entry2, ...]
  ^BIJ("control") = {seq_no, open_tx, ...}

Autor: Hermes + CadencesLab (MSM-01)
Licencia: MIT (lumen-protocol)
"""

import sys, os, json
from datetime import datetime, timezone

BIJ_NS = "BIJ"

def _get_tools():
    pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order, tool_kill
    return tool_set, tool_get, tool_order, tool_kill

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _now_ns():
    return datetime.now(timezone.utc).timestamp() * 1_000_000_000

def bij_init():
    """Inicializar control block de BIJ (como BIJFMT init)."""
    tool_set, tool_get, _, _ = _get_tools()
    r = tool_get({"ns": BIJ_NS, "subs": ["control"]})
    if r.get("value"):
        return r["value"]
    ctrl = {
        "seq_no": 0,
        "open_tx": 0,
        "rolled_back": 0,
        "committed": 0,
        "created": _now_iso(),
    }
    tool_set({"ns": BIJ_NS, "subs": ["control"], "value": ctrl})
    return ctrl

def bij_record(ns, subs, old_value, tx_id=None):
    """Guardar before-image de una operación (llamar ANTES de modificar).
    
    Como BIJ de MSM: guarda el valor anterior antes de SET/KILL.
    """
    tool_set, tool_get, _, _ = _get_tools()
    ctrl = bij_init()
    ctrl["seq_no"] += 1
    seq = ctrl["seq_no"]
    tx_id = tx_id or f"tx_{_now_ns()}"

    entry = {
        "tx_id": tx_id,
        "ns": ns,
        "subs": subs,
        "old_value": old_value,
        "timestamp": _now_iso(),
        "status": "pending",
        "seq": seq,
    }

    # Guardar en ^BIJ("file", seq)
    tool_set({"ns": BIJ_NS, "subs": ["file", seq], "value": entry})

    # Guardar en ^BIJ("tx", tx_id, seq)
    tool_set({"ns": BIJ_NS, "subs": ["tx", tx_id, int(seq)], "value": entry})

    # Actualizar control
    tool_set({"ns": BIJ_NS, "subs": ["control"], "value": ctrl})

    return entry

def bij_commit(tx_id):
    """Marcar una transacción como completada.
    Los before-images ya no son necesarios → se archivan.
    """
    tool_set, tool_get, _, _ = _get_tools()
    seq = 0
    while True:
        r = tool_order({"ns": BIJ_NS, "subs": ["tx", tx_id, seq], "direction": 1})
        if not r.get("success") or r.get("value") is None:
            break
        seq = r["value"]
        r2 = tool_get({"ns": BIJ_NS, "subs": ["tx", tx_id, seq]})
        if r2.get("success") and r2.get("value"):
            entry = r2["value"]
            entry["status"] = "committed"
            tool_set({"ns": BIJ_NS, "subs": ["tx", tx_id, seq], "value": entry})
            # Marcar en file también
            f_seq = entry.get("seq")
            if f_seq:
                tool_set({"ns": BIJ_NS, "subs": ["file", f_seq, "status"], "value": "committed"})

    ctrl = bij_init()
    ctrl["committed"] += 1
    tool_set({"ns": BIJ_NS, "subs": ["control"], "value": ctrl})

def bij_rollback(tx_id):
    """ROLLBACK: restaurar todos los before-images de una transacción.
    
    Como MSM BIJ: recupera old_value y hace SET para restaurar.
    """
    tool_set, tool_get, tool_order, tool_kill = _get_tools()
    seq = 0
    restored = 0

    while True:
        r = tool_order({"ns": BIJ_NS, "subs": ["tx", tx_id, seq], "direction": 1})
        if not r.get("success") or r.get("value") is None:
            break
        seq = r["value"]
        r2 = tool_get({"ns": BIJ_NS, "subs": ["tx", tx_id, seq]})
        if r2.get("success") and r2.get("value"):
            entry = r2["value"]
            if entry.get("status") == "committed":
                continue  # ya confirmado, no hacer rollback

            ns = entry["ns"]
            subs = entry["subs"]
            old_val = entry["old_value"]

            # Restaurar old_value
            if old_val is not None:
                tool_set({"ns": ns, "subs": subs, "value": old_val})
            else:
                tool_kill({"ns": ns, "subs": subs})

            entry["status"] = "rolled_back"
            tool_set({"ns": BIJ_NS, "subs": ["tx", tx_id, seq], "value": entry})
            restored += 1

    ctrl = bij_init()
    ctrl["rolled_back"] += 1
    tool_set({"ns": BIJ_NS, "subs": ["control"], "value": ctrl})
    return restored

def bij_status():
    """Estado del BIJ (como BIJFMT display)."""
    _, tool_get, _, _ = _get_tools()
    ctrl = tool_get({"ns": BIJ_NS, "subs": ["control"]})
    c = ctrl.get("value") if ctrl.get("success") else bij_init()
    return {
        "seq_no": c.get("seq_no", 0),
        "open_tx": c.get("open_tx", 0),
        "committed": c.get("committed", 0),
        "rolled_back": c.get("rolled_back", 0),
        "pending": c.get("seq_no", 0) - c.get("committed", 0) - c.get("rolled_back", 0),
    }

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "init":
        bij_init()
        print("BIJ initialized")

    elif cmd == "record":
        ns = sys.argv[2]; subs = sys.argv[3].split(",")
        old = sys.argv[4] if len(sys.argv) > 4 else None
        tx = sys.argv[5] if len(sys.argv) > 5 else None
        e = bij_record(ns, subs, old, tx)
        print(f"Recorded: {e['ns']}{e['subs']} = {str(e['old_value'])[:30]}")

    elif cmd == "commit":
        tx = sys.argv[2]
        bij_commit(tx)
        print(f"Committed: {tx}")

    elif cmd == "rollback":
        tx = sys.argv[2]
        n = bij_rollback(tx)
        print(f"Rollback {tx}: {n} entries restored")

    else:
        s = bij_status()
        print(f"📊 BIJ Status:")
        for k, v in s.items():
            print(f"  {k}: {v}")
