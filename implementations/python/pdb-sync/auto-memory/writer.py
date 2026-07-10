"""
extract_learnings — Writer (PDB via pdb-edge-worker)

Paso 4 del pipeline: escribe los facts validados en PDB bajo
^System("learnings") usando la REST API del pdb-edge-worker (Cloudflare D1).

Cada aprendizaje se almacena como:
    ^System("learnings", learning_<uuid12>) → JSON con metadata completo

API: POST /v1/set/System  {key: "learnings/learning_xxx", value: "<json>"}
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any

# ─── Configuración ──────────────────────────────────────────────────

PDB_EDGE_WORKER_URL = "https://pdb-edge.gonzalomonzonc.workers.dev"  # CF D1 edge worker
LEARNINGS_NAMESPACE = "learnings"
CONFIDENCE_THRESHOLD = 6  # Zalo: descartar facts con confianza < 6


async def write_learnings_to_pdb(
    facts: list[dict[str, Any]],
    session_id: str,
) -> dict[str, int]:
    """
    Escribe facts validados en PDB bajo ^System("learnings").

    Args:
        facts: Lista de facts con metadata de validación (confianza, is_duplicate)
        session_id: Identificador de la sesión (ej: "hermes_20260711_1430")

    Returns:
        {written, skipped_duplicates, skipped_low_confidence, errors}
    """
    stats = {
        "written": 0,
        "skipped_duplicates": 0,
        "skipped_low_confidence": 0,
        "errors": 0,
    }

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for fact in facts:
        # ── Filtros ──
        if fact.get("is_duplicate"):
            stats["skipped_duplicates"] += 1
            continue

        confianza = fact.get("confianza", 5)
        if confianza < CONFIDENCE_THRESHOLD:
            stats["skipped_low_confidence"] += 1
            continue

        # ── Construir registro ──
        learning_id = f"learning_{uuid.uuid4().hex[:12]}"
        record = {
            "hecho": fact["hecho"],
            "confianza": confianza,
            "tipo": fact.get("tipo", "project"),
            "fuente": session_id,
            "tags": fact.get("tags", []),
            "timestamp": now_iso,
            "validado_por": "zalo",
            "extraido_por": "tom",
            "raw_context": fact.get("raw_context", ""),
            "validacion_razon": fact.get("validacion_razon", ""),
        }

        # ── Escribir a PDB ──
        success = await _pdb_set(
            key=f"{LEARNINGS_NAMESPACE}/{learning_id}",
            value=json.dumps(record, ensure_ascii=False),
        )

        if success:
            stats["written"] += 1
        else:
            stats["errors"] += 1

    return stats


async def _pdb_set(key: str, value: str) -> bool:
    """
    Escribe un key/value en PDB vía pdb-edge-worker REST API.

    Endpoint: POST /v1/set/System
    Body: {"key": "learnings/learning_xxx", "value": "<json>"}
    """
    try:
        import httpx
    except ImportError:
        print("[WARN] httpx no instalado — no se puede escribir a PDB")
        return False

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{PDB_EDGE_WORKER_URL}/v1/set/System",
                json={"key": key, "value": value},
            )
            if resp.status_code in (200, 201):
                return True
            print(f"[WARN] PDB write failed ({resp.status_code}): {resp.text[:200]}")
            return False
    except httpx.ConnectError:
        print(f"[ERROR] Cannot connect to pdb-edge-worker at {PDB_EDGE_WORKER_URL}")
        return False
    except Exception as e:
        print(f"[ERROR] PDB write exception: {e}")
        return False
