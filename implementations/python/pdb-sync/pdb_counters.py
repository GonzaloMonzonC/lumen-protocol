#!/usr/bin/env python3
"""
pdb_counters.py — MSM-06: COUNTERS adaptado.

Métricas de rendimiento del sistema PDB. Como COUNTERS (73 líneas) de MSM:
  - Operaciones por namespace (SETs/KILLs)
  - Eficiencia de escritura (full vs partial writes)
  - Estado del journal (seq_no, healthy)
  - Top namespaces por actividad

Integrado con:
  ^CHANGES("control") — control block del journal (A1)
  ^System("pulse") — heartbeats de agentes
  ^System("errors","catalog") — contador de errores

Autor: Hermes + CadencesLab (MSM-06)
Licencia: MIT
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

def get_journal_stats():
    """Estadísticas del journal (SETs/KILLs/eficiencia)."""
    _, tool_get, _ = _get_tools()
    r = tool_get({"ns": "CHANGES", "subs": ["control"]})
    ctrl = r.get("value") if r.get("success") else {}
    
    sets = ctrl.get("sets", 0)
    kills = ctrl.get("kills", 0)
    full = ctrl.get("full_writes", 0)
    partial = ctrl.get("partial_writes", 0)
    total_ops = sets + kills
    total_writes = full + partial
    
    return {
        "sets": sets,
        "kills": kills,
        "total_ops": total_ops,
        "ratio_s_k": round(sets / max(kills, 1), 2),
        "full_writes": full,
        "partial_writes": partial,
        "write_efficiency": round(full / max(total_writes, 1) * 100, 1),
        "seq_no": ctrl.get("seq_no", 0),
        "healthy": ctrl.get("status", 0) == 0 if ctrl else True,
    }

def get_agent_stats():
    """Estadísticas de agentes activos."""
    _, tool_get, tool_order = _get_tools()
    agents = {"online": 0, "busy": 0, "offline": 0}
    key = ""
    while True:
        r = tool_order({"ns": "System", "subs": ["pulse", key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        r2 = tool_get({"ns": "System", "subs": ["pulse", key]})
        if r2.get("success") and r2.get("value"):
            status = r2["value"].get("status", "offline")
            agents[status] = agents.get(status, 0) + 1
    return agents

def counters_report():
    """Reporte completo como COUNTERS^%ET de MSM."""
    journal = get_journal_stats()
    agents = get_agent_stats()
    
    lines = [
        "╔═══════════════════════════════════╗",
        "║   PDB COUNTERS (MSM-style)       ║",
        "╚═══════════════════════════════════╝",
        f"",
        f"📊 JOURNAL:",
        f"   Total ops:    {journal['total_ops']:>8}",
        f"   SETs:         {journal['sets']:>8}",
        f"   KILLs:        {journal['kills']:>8}",
        f"   Ratio S/K:    {journal['ratio_s_k']:>8.2f}",
        f"   Write eff:    {journal['write_efficiency']:>7.1f}%",
        f"   Seq no:       {journal['seq_no']:>8}",
        f"   Healthy:      {str(journal['healthy']):>8}",
        f"",
        f"🤖 AGENTS:",
        f"   Online:       {agents.get('online', 0):>8}",
        f"   Busy:         {agents.get('busy', 0):>8}",
        f"   Offline:      {agents.get('offline', 0):>8}",
        f"   Total:        {sum(agents.values()):>8}",
    ]
    return "\n".join(lines)

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "report":
        print(counters_report())
    elif cmd == "json":
        import json
        print(json.dumps({"journal": get_journal_stats(), "agents": get_agent_stats()}, indent=2))
