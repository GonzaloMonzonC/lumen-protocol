#!/usr/bin/env python3
"""
pdb_job_monitor.py — C3: Job Monitor (%ACTJOB pattern).

Inspirado en %ACTJOB (34 líneas) de MSM:
  ACTIVE(JOB) — 1 si job activo
  LIST(JLIST) — lista de jobs activos
  NEXT(JLIST,JOB) — iterar

Nuestro:
  - "Jobs" = agentes en ^System("pulse")
  - "Active" = agentes con heartbeat < 60s
  - Monitoriza micro-status, carga, tareas pendientes

Autor: Hermes + CadencesLab (C3 — Sprint C MSM→Lumen)
Licencia: MIT
"""

import sys, os
import _paths  # rutas repo-relativas
from datetime import datetime, timezone, timedelta

def _get_tools():
    pdb_dir = _paths.PDB_DIR_S
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order
    return tool_set, tool_get, tool_order

def _now():
    return datetime.now(timezone.utc)

def _now_iso():
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")

def active(agent_id):
    """ACTIVE(JOB): 1 si agente activo."""
    _, tool_get, _ = _get_tools()
    r = tool_get({"ns": "System", "subs": ["pulse", agent_id]})
    p = r.get("value") if r.get("success") else None
    if not p: return 0
    last = p.get("last_activity") or p.get("last_heartbeat", "")
    try:
        age = (_now() - datetime.fromisoformat(last.replace("Z","+00:00"))).total_seconds()
        return 1 if age < 120 else 0
    except: return 0

def job_list():
    """LIST(JLIST): lista de todos los agentes con estado."""
    _, tool_get, tool_order = _get_tools()
    jobs = []
    key = ""
    while True:
        r = tool_order({"ns": "System", "subs": ["pulse", key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        r2 = tool_get({"ns": "System", "subs": ["pulse", key]})
        p = r2.get("value") if r2.get("success") else {}
        jobs.append({
            "agent": key,
            "status": p.get("status", "unknown"),
            "load": p.get("load", 0),
            "micro_status": p.get("micro_status", ""),
            "active": active(key),
            "last_activity": p.get("last_activity", ""),
        })
    return jobs

def job_summary():
    """Resumen tipo %ACTJOB."""
    jobs = job_list()
    active_count = sum(j["active"] for j in jobs)
    total = len(jobs)
    by_status = {}
    for j in jobs:
        s = j["status"]
        by_status[s] = by_status.get(s, 0) + 1

    return {
        "total": total,
        "active": active_count,
        "by_status": by_status,
        "load_avg": sum(j["load"] for j in jobs) / max(total, 1),
    }

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        for j in job_list():
            e = {"online":"🟢","busy":"🟡","idle":"⏸️","offline":"🔴"}.get(j["status"],"❓")
            ms = f" — {j['micro_status']}" if j.get('micro_status') else ""
            print(f"  {e} {j['agent']:10s} {j['status']:8s} load={j['load']}{ms}")
    elif cmd == "active":
        for j in job_list():
            if j["active"]:
                print(f"  🟢 {j['agent']}")
    else:
        s = job_summary()
        print(f"📊 {s['active']}/{s['total']} activos | load avg: {s['load_avg']:.1f}")
        for st, ct in s["by_status"].items():
            print(f"  {st}: {ct}")
