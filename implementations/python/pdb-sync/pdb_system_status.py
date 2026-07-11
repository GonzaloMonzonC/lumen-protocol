#!/usr/bin/env python3
"""
pdb_system_status.py — System Status (%SS adaptado).

Monitor de sistema tipo htop para el ecosistema PDB.
Integra: COUNTERS, Job Monitor, Network Agent, Agent Workspace.

Inspirado en %SS (177 líneas) de MSM:
  - Max Partitions / Current in Use
  - Jobs activos con su estado
  - Buffers del sistema
  - Dispositivos conectados

Nuestra versión:
  - Agentes online/offline con micro-status
  - Operaciones PDB (SETs/KILLs/seq_no)
  - Circuitos DDP activos
  - Errores recientes

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os
from datetime import datetime, timezone

def _get_tools():
    pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order
    return tool_set, tool_get, tool_order

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── System Status ─────────────────────────────────────────────────

def ss_agents():
    """Agentes: como %SS muestra jobs activos."""
    _, tool_get, tool_order = _get_tools()
    agents = []
    key = ""
    while True:
        r = tool_order({"ns": "System", "subs": ["pulse", key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        r2 = tool_get({"ns": "System", "subs": ["pulse", key]})
        if r2.get("success") and r2.get("value"):
            p = r2["value"]
            agents.append({
                "id": key,
                "status": p.get("status", "?"),
                "load": p.get("load", 0),
                "task": p.get("micro_status", ""),
                "last_seen": p.get("last_activity", ""),
            })
    return agents

def ss_journal():
    """Estadísticas del journal (como %SS muestra buffers)."""
    _, tool_get, _ = _get_tools()
    r = tool_get({"ns": "CHANGES", "subs": ["control"]})
    c = r.get("value") if r.get("success") else {}
    return {
        "sets": c.get("sets", 0),
        "kills": c.get("kills", 0),
        "seq_no": c.get("seq_no", 0),
        "full_writes": c.get("full_writes", 0),
        "healthy": c.get("status", "healthy") == "healthy" or c.get("status", 1) == 1,
    }

def ss_errors():
    """Errores recientes del sistema."""
    _, tool_get, tool_order = _get_tools()
    errors = []
    key = ""
    while True:
        r = tool_order({"ns": "System", "subs": ["errors", key], "direction": -1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        r2 = tool_get({"ns": "System", "subs": ["errors", key]})
        if r2.get("success") and r2.get("value"):
            e = r2["value"]
            errors.append(e.get("error", str(e)[:60]))
            if len(errors) >= 5: break
    return errors

def ss_dashboard():
    """Dashboard completo como %SS display."""
    agents = ss_agents()
    journal = ss_journal()
    errors = ss_errors()

    lines = [
        "╔═══════════════════════════════════════╗",
        "║   PDB SYSTEM STATUS (%SS) [ HTOP ]    ║",
        "╚═══════════════════════════════════════╝",
        "",
        f"📊 JOURNAL:",
        f"   Ops: {journal['sets'] + journal['kills']:>6}  SETs={journal['sets']}  KILLs={journal['kills']}",
        f"   Seq: {journal['seq_no']:>6}  Full writes: {journal['full_writes']}",
        f"   Healthy: {str(journal['healthy']):>6}",
        "",
        f"🤖 AGENTS ({len(agents)}):",
    ]

    for a in agents:
        icon = {"online":"🟢","busy":"🟡","idle":"⏸️","offline":"🔴"}.get(a["status"], "❓")
        task = f" — {a['task']}" if a.get("task") else ""
        lines.append(f"   {icon} {a['id']:10s} {a['status']:8s} load={a['load']}{task}")

    if errors:
        lines.append(f"\n⚠️  ERRORS ({len(errors)}):")
        for e in errors:
            lines.append(f"   🔴 {str(e)[:70]}")

    return "\n".join(lines)

if __name__ == "__main__":
    print(ss_dashboard())
