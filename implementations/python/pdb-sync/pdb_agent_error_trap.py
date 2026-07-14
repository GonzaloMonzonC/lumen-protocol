#!/usr/bin/env python3
"""
pdb_agent_error_trap.py — %ET para agentes CadencesLab.

Cuando un agente falla:
  1. Captura error + stack trace
  2. Snapshot del contexto (pulse, decisiones, tareas pendientes)
  3. Guarda todo en ^System("errors", agent_id, timestamp)
  4. Notifica al Service Manager para posible reinicio

Inspirado en %ET (92 líneas) de MSM:
  ^UTILITY("%ER",hash,entry) = error_context

Nuestro:
  ^System("errors", agent_id, timestamp) = {
    error: "$ZE",
    stack: [...],
    pulse: {...},
    decisions: [...],
    tasks: [...]
  }

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, traceback
import _paths  # rutas repo-relativas
from datetime import datetime, timezone

def _get_tools():
    pdb_dir = _paths.PDB_DIR_S
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get
    return tool_set, tool_get

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def capture_agent_error(agent_id, error_msg, exception=None):
    """Capturar el estado de un agente cuando falla.
    
    Como %ET: salva $ZE, $STACK, y dump de variables.
    
    Args:
        agent_id: nombre del agente (hermes, zalo, etc.)
        error_msg: mensaje de error ($ZE)
        exception: opcional, objeto Exception de Python
    """
    tool_set, tool_get = _get_tools()
    ts = _now_iso()
    ts_safe = ts.replace(":", "-").replace(".", "-")

    # 1. Error context (como $ZE + $ECODE)
    context = {
        "error": error_msg,
        "timestamp": ts,
        "agent": agent_id,
    }

    # 2. Stack trace (como $STACK)
    if exception:
        context["stack"] = traceback.format_exception(type(exception), exception, exception.__traceback__)
        context["stack_summary"] = traceback.format_exception_only(type(exception), exception)
    else:
        context["stack"] = traceback.format_stack()
        context["stack_summary"] = [error_msg]

    # 3. Snapshot de pulse (como dump de variables locales en %ET)
    r = tool_get({"ns": "System", "subs": ["pulse", agent_id]})
    context["pulse"] = r.get("value") if r.get("success") else "N/A"

    # 4. Decisiones recientes
    from pdb_tools import tool_order
    decisions = []
    key = ""
    while True:
        r2 = tool_order({"ns": "System", "subs": ["decisions", key], "direction": -1})
        if not r2.get("success") or r2.get("value") is None: break
        key = r2["value"]
        r3 = tool_get({"ns": "System", "subs": ["decisions", key]})
        if r3.get("success") and r3.get("value"):
            decision = r3["value"]
            if isinstance(decision, dict) and decision.get("agent") == agent_id:
                decisions.append(decision)
                if len(decisions) >= 5: break
    context["recent_decisions"] = decisions

    # 5. Guardar en ^System("errors", agent, timestamp)
    tool_set({"ns": "System", "subs": ["errors", agent_id, ts_safe], "value": context})

    # 6. Registrar en ^System("errors", "index") para búsqueda rápida
    tool_set({"ns": "System", "subs": ["errors", "index", ts_safe], "value": {
        "agent": agent_id,
        "error": error_msg[:80],
        "timestamp": ts,
    }})

    return ts_safe

def get_agent_errors(agent_id=None, limit=10):
    """Leer errores de un agente (o todos)."""
    _, tool_get = _get_tools()
    from pdb_tools import tool_order

    errors = []
    agents = [agent_id] if agent_id else []

    # Obtener lista de agentes si no se especificó
    if not agents:
        key = ""
        while True:
            r = tool_order({"ns": "System", "subs": ["errors", key], "direction": -1})
            if not r.get("success") or r.get("value") is None: break
            key = r["value"]
            if key == "index": continue
            agents.append(key)

    # Iterar errores de cada agente
    for agent in agents:
        ts_key = ""
        while True:
            r = tool_order({"ns": "System", "subs": ["errors", agent, ts_key], "direction": -1})
            if not r.get("success") or r.get("value") is None: break
            ts_key = r["value"]
            r2 = tool_get({"ns": "System", "subs": ["errors", agent, ts_key]})
            if r2.get("success") and r2.get("value"):
                errors.append(r2["value"])
                if len(errors) >= limit: return errors
    return errors

def clear_errors(agent_id=None):
    """Limpiar errores de un agente (o todos)."""
    from pdb_tools import tool_kill, tool_order
    if agent_id:
        tool_kill({"ns": "System", "subs": ["errors", agent_id]})
        return f"Cleared errors for {agent_id}"
    else:
        tool_kill({"ns": "System", "subs": ["errors"]})
        return "Cleared all errors"

def error_summary():
    """Resumen de errores recientes (como %ET muestra resumen)."""
    errors = get_agent_errors(limit=20)
    if not errors:
        return "✅ No errors recorded"
    
    lines = [f"⚠️ {len(errors)} errores registrados:"]
    for e in errors:
        agent = e.get("agent", "?")
        err = str(e.get("error", "?"))[:60]
        ts = e.get("timestamp", "?")[:19]
        lines.append(f"  🔴 {agent:10s} [{ts}] {err}")
    return "\n".join(lines)

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    
    if cmd == "capture":
        agent = sys.argv[2]
        msg = sys.argv[3] if len(sys.argv) > 3 else "No error message"
        try:
            raise RuntimeError(msg)
        except RuntimeError as e:
            ts = capture_agent_error(agent, msg, e)
            print(f"✅ Error captured for {agent} @ {ts}")
    elif cmd == "list":
        agent = sys.argv[2] if len(sys.argv) > 2 else None
        for e in get_agent_errors(agent):
            print(f"  🔴 {e.get('agent','?')}: {str(e.get('error',''))[:80]}")
    elif cmd == "clear":
        agent = sys.argv[2] if len(sys.argv) > 2 else None
        print(clear_errors(agent))
    else:
        print(error_summary())
