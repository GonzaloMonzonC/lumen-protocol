#!/usr/bin/env python3
"""
pdb-micro-status — 3-5 words micro-status en ^System("pulse").

CC4: Cada agente reporta qué está haciendo en presente continuo.
Basado en AgentSummary de Claude Code, adaptado a PDB compartida.

Schema:
    ^System("pulse","<agente>","micro_status") = "Processing classification"
    ^System("pulse","<agente>","micro_status_at") = "2026-07-11T15:00:00Z"

Uso:
    python pdb_micro_status.py --agent tom --status "Classifying intent tokens"
    python pdb_micro_status.py --agent hermes --auto  # genera con LLM

Author: Hermes + CadencesLab (CC4 — Claude Code learnings)
Date: 2026-07-11
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

# ── Config ──────────────────────────────────────────────────────────

PDB_EDGE_URL = os.environ.get("PDB_EDGE_URL", "https://pdb-edge.gonzalomonzonc.workers.dev")
PDB_EDGE_KEY = os.environ.get("PDB_EDGE_KEY", "pdb_hermes_2026")

# ── Helpers ──────────────────────────────────────────────────────────

def get_pdb_tools():
    """Importar pdb_tools desde el path correcto."""
    pdb_path = os.path.expanduser(
        "~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"
    )
    sys.path.insert(0, pdb_path)
    from pdb_tools import tool_set
    return tool_set

# ── Micro Status ─────────────────────────────────────────────────────

def set_micro_status(agent_id, status_text):
    """Escribir micro_status en ^System("pulse")."""
    tool_set = get_pdb_tools()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Escribir en PDB local → pdb-sync-bridge lo replicará al Edge
    result = tool_set({
        "ns": "System",
        "subs": ["pulse", agent_id, "micro_status"],
        "value": status_text
    })
    # También actualizar timestamp
    tool_set({
        "ns": "System",
        "subs": ["pulse", agent_id, "micro_status_at"],
        "value": now
    })

    if result.get("success"):
        print(f"[micro-status] 📝 {agent_id}: \"{status_text}\" ({now})")
    else:
        print(f"[micro-status] ❌ {agent_id}: {result.get('error')}")

    return result

# ── Auto-generate via LLM ────────────────────────────────────────────

def auto_micro_status(agent_id, task_description):
    """Generar micro_status automáticamente con LLM (3-5 words, -ing form)."""
    # Usar Tom (Granite) para generación rápida
    prompt = f"Describe this task in exactly 3-5 words, present tense (-ing form): \"{task_description}\". Return ONLY the phrase, no quotes, no explanation."

    # En producción, esto llamaría a mcp_tom_tom_process(tier="GRANITE")
    # Para MVP, usamos una heurística simple
    verbs = {
        "classif": "Classifying",
        "summar": "Summarizing",
        "extract": "Extracting",
        "process": "Processing",
        "analyz": "Analyzing",
        "generat": "Generating",
        "search": "Searching",
        "fetch": "Fetching",
        "writ": "Writing",
        "deploy": "Deploying",
        "build": "Building",
        "test": "Testing",
        "sync": "Syncing",
    }
    desc_lower = task_description.lower()
    verb = "Processing"
    for key, v in verbs.items():
        if key in desc_lower:
            verb = v
            break

    # Extraer objeto (primeras 2-3 palabras significativas después del verbo)
    words = task_description.split()
    obj = " ".join(words[1:4]) if len(words) > 1 else "task"
    if len(obj) > 25:
        obj = obj[:25] + "..."

    return f"{verb} {obj}"

# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    agent = None
    status = None
    auto = False

    for i, arg in enumerate(sys.argv):
        if arg == "--agent" and i + 1 < len(sys.argv):
            agent = sys.argv[i + 1]
        elif arg == "--status" and i + 1 < len(sys.argv):
            status = sys.argv[i + 1]
        elif arg == "--auto" and i + 1 < len(sys.argv):
            auto = True
            status = sys.argv[i + 1] if i + 1 < len(sys.argv) else None

    if not agent:
        print("Uso: python pdb_micro_status.py --agent <nombre> --status \"texto\"")
        print("      python pdb_micro_status.py --agent <nombre> --auto \"descripción tarea\"")
        sys.exit(1)

    if auto and status:
        status = auto_micro_status(agent, status)

    if not status:
        print("Error: --status o --auto requerido")
        sys.exit(1)

    set_micro_status(agent, status)
