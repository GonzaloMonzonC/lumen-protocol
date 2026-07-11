#!/usr/bin/env python3
"""
pdb_error_catalog.py — MSM-04: %ERRCODE adaptado + errores de agente.

Catálogo unificado de códigos de error en ^System("errors","catalog").
Incluye MSM + agentes CadencesLab + M-Light.
"""
import sys, os, re
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))

MSM_ERRORS = {}

def _extract_msm_errors():
    from pdb_tools import tool_get
    for i in range(1, 350):
        r = tool_get({"ns": "ROUTINE", "subs": ["%ERRCODE", i]})
        if not r.get("success") or not r.get("value"): break
        line = r["value"]
        m = re.match(r'^\s*(\S+)\s*;\s*(.*)', line)
        if m:
            code = m.group(1).strip()
            desc = m.group(2).strip()
            if desc and desc not in ("ERR", "EXIT", ""):
                MSM_ERRORS[code] = {"description": desc, "source": "MSM"}

AGENT_ERRORS = {
    "AG-001": {"description": "Timeout DDP: agente no responde", "source": "DDP", "severity": "error"},
    "AG-002": {"description": "HMAC signature mismatch", "source": "Security", "severity": "critical"},
    "AG-003": {"description": "Enlace DDP no configurado", "source": "DDP", "severity": "error"},
    "PDB-001": {"description": "Namespace no encontrado", "source": "PDB", "severity": "error"},
    "PDB-002": {"description": "Valor corrupto en ^CHANGES", "source": "Journal", "severity": "warning"},
    "PDB-003": {"description": "Checkpoint inconsistente", "source": "Recovery", "severity": "warning"},
    "H-001": {"description": "Tarea no planificada", "source": "Hermes", "severity": "warning"},
    "Z-001": {"description": "KB no actualizado", "source": "Zalo", "severity": "warning"},
    "L-001": {"description": "Orquestación incompleta", "source": "Lisa", "severity": "warning"},
    "T-001": {"description": "Procesamiento timeout", "source": "Tom", "severity": "error"},
    "ML-001": {"description": "Variable no definida en M-Light", "source": "MLight", "severity": "warning"},
}

def error_catalog_init():
    from pdb_tools import tool_set
    _extract_msm_errors()
    for code, info in MSM_ERRORS.items():
        tool_set({"ns": "System", "subs": ["errors", "catalog", code], "value": info})
    for code, info in AGENT_ERRORS.items():
        tool_set({"ns": "System", "subs": ["errors", "catalog", code], "value": info})
    tool_set({"ns": "System", "subs": ["errors", "catalog", "_meta"], "value": {
        "msm_count": len(MSM_ERRORS), "agent_count": len(AGENT_ERRORS),
        "total": len(MSM_ERRORS) + len(AGENT_ERRORS),
    }})
    return len(MSM_ERRORS) + len(AGENT_ERRORS)

def error_catalog_lookup(code):
    from pdb_tools import tool_get
    r = tool_get({"ns": "System", "subs": ["errors", "catalog", code]})
    return r.get("value") if r.get("success") else {"description": f"Unknown: {code}"}

if __name__ == "__main__":
    n = error_catalog_init()
    print(f"✅ Catálogo: {n} códigos ({len(MSM_ERRORS)} MSM + {len(AGENT_ERRORS)} agentes)")
    for code in sorted(AGENT_ERRORS.keys())[:3]:
        info = error_catalog_lookup(code)
        print(f"  {code}: {info.get('description')}")
