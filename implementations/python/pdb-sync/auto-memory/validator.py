"""
extract_learnings — Validator (Zalo / Qwen32B)

Paso 3 del pipeline: Zalo revisa cada hecho extraído por Tom y asigna:
- confianza (1-10): qué tan correcto y útil es
- is_duplicate: si ya existe en PDB
- razon: justificación breve

Zalo usa Qwen32B: más potencia que Granite, ideal para juicio crítico.
"""

import json
from typing import Any

from prompts import VALIDATION_SYSTEM_PROMPT, VALIDATION_USER_TEMPLATE


async def validate_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Zalo valida cada hecho del batch.
    Retorna los mismos facts enriquecidos con confianza, is_duplicate, validacion_razon.

    Args:
        facts: Lista de facts extraídos por Tom

    Returns:
        Misma lista con campos añadidos: confianza, is_duplicate, validacion_razon
    """
    if not facts:
        return []

    # Formatear facts para que Zalo los evalúe uno por uno
    facts_text = "\n\n".join(
        f"FACT {i + 1}:\n"
        f"  hecho: {f['hecho']}\n"
        f"  tipo: {f['tipo']}\n"
        f"  tags: {f.get('tags', [])}\n"
        f"  context: {f.get('raw_context', '')[:300]}"
        for i, f in enumerate(facts)
    )

    full_prompt = (
        VALIDATION_SYSTEM_PROMPT
        + "\n\n---\n\n"
        + VALIDATION_USER_TEMPLATE.format(facts_text=facts_text)
    )

    # ── Llamada a Zalo vía MCP ──
    try:
        from mcp_zalo import zalo_chat  # type: ignore[import-untyped]
        response = await zalo_chat(mensaje=full_prompt)
        validations = _parse_llm_json(response)
    except ImportError:
        print("[WARN] Zalo MCP no disponible — usando stub (confianza=5)")
        validations = [
            {"confianza": 5, "is_duplicate": False, "razon": "validation_unavailable"}
            for _ in facts
        ]
    except Exception as e:
        print(f"[ERROR] Zalo validation failed: {e}")
        validations = [
            {"confianza": 5, "is_duplicate": False, "razon": f"error: {str(e)[:50]}"}
            for _ in facts
        ]

    # Merge: enriquecer cada fact con su validación
    for i, f in enumerate(facts):
        if i < len(validations):
            v = validations[i]
            f["confianza"] = _clamp_confidence(v.get("confianza", 5))
            f["is_duplicate"] = bool(v.get("is_duplicate", False))
            f["validacion_razon"] = str(v.get("razon", ""))
        else:
            f["confianza"] = 5
            f["is_duplicate"] = False
            f["validacion_razon"] = ""

    return facts


def _clamp_confidence(value: Any) -> int:
    """Asegura que la confianza esté en [1, 10]."""
    try:
        c = int(value)
        return max(1, min(10, c))
    except (ValueError, TypeError):
        return 5


def _parse_llm_json(raw: str) -> list[dict[str, Any]]:
    """Parseo robusto (misma lógica que extractor)."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines)
    if not raw.startswith("[") and not raw.startswith("{"):
        for i, ch in enumerate(raw):
            if ch in ("[", "{"):
                raw = raw[i:]
                break
    if raw.startswith("["):
        last_bracket = raw.rfind("]")
        if last_bracket > 0:
            raw = raw[: last_bracket + 1]
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
        return []
    except json.JSONDecodeError:
        return []
