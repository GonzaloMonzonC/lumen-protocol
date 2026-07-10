"""
extract_learnings — Extractor (Tom / Granite8B)

Paso 1+2 del pipeline: llama a Tom para extraer hechos del transcript
y parsea el JSON resultante de forma robusta.

Tom usa Granite8B: ultra-barato, ideal para esta tarea de clasificación.
"""

import json
from typing import Any


async def extract_facts_from_transcript(transcript: str) -> list[dict[str, Any]]:
    """
    Llama a Tom (Granite8B) para extraer hechos del transcript.

    Args:
        transcript: Texto completo de la conversación

    Returns:
        Lista de facts en bruto: [{hecho, tipo, tags, raw_context}, ...]
        Lista vacía si no se encuentra nada extractable.
    """
    # ── Integración con Tom vía MCP ──
    # Tom está disponible como mcp_tom_tom_extract(text, schema)
    # Usamos la tool directamente desde el agente Hermes

    from prompts import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_TEMPLATE

    schema_desc = (
        "array of objects with keys: "
        "hecho (string, one-sentence fact in Spanish), "
        "tipo (one of: user, feedback, project, reference), "
        "tags (array of strings), "
        "raw_context (string, exact transcript excerpt that supports this fact)"
    )

    # Combinar system + user prompt para Tom
    full_text = (
        EXTRACTION_SYSTEM_PROMPT
        + "\n\n---\n\n"
        + EXTRACTION_USER_TEMPLATE.format(transcript=transcript)
        + f"\n\nSchema: {schema_desc}"
    )

    # ── Llamada a Tom ──
    # NOTA: En producción, esta llamada usa mcp_tom_tom_extract()
    # Aquí se documenta la interfaz esperada:
    #
    #   raw = await mcp_tom_tom_extract(text=full_text, schema=schema_desc)
    #
    # Tom devuelve un string con JSON (posiblemente envuelto en ```json)

    try:
        # Placeholder — reemplazar con llamada real a Tom
        from mcp_tom import tom_extract  # type: ignore[import-untyped]
        raw = await tom_extract(text=full_text, schema=schema_desc)
    except ImportError:
        # Fallback para testing sin Tom disponible
        print("[WARN] Tom MCP no disponible — usando stub")
        return []

    facts = _parse_llm_json(raw)

    # Validación estructural post-extracción
    valid_facts = []
    for f in facts:
        if not isinstance(f, dict):
            continue
        if "hecho" not in f or not str(f["hecho"]).strip():
            continue
        if f.get("tipo") not in ("user", "feedback", "project", "reference"):
            f["tipo"] = "project"  # default fallback
        if "tags" not in f or not isinstance(f["tags"], list):
            f["tags"] = []
        if "raw_context" not in f:
            f["raw_context"] = ""
        valid_facts.append(f)

    return valid_facts


def _parse_llm_json(raw: str) -> list[dict[str, Any]]:
    """
    Parseo robusto de JSON devuelto por un LLM.
    Soporta: JSON puro, JSON envuelto en ```json ```, JSON con texto antes/después.
    """
    raw = raw.strip()

    # Caso 1: Code block markdown
    if raw.startswith("```"):
        lines = raw.split("\n")
        # Eliminar primera y última línea si son ```
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines)

    # Caso 2: JSON incrustado en texto — buscar primer [ o {
    if not raw.startswith("[") and not raw.startswith("{"):
        for i, ch in enumerate(raw):
            if ch in ("[", "{"):
                raw = raw[i:]
                break

    # Caso 3: Solo tomar hasta el último ] o }
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
    except json.JSONDecodeError as e:
        print(f"[ERROR] Failed to parse Tom JSON: {e}")
        print(f"[DEBUG] Raw response (first 500 chars): {raw[:500]}")
        return []
