"""
extractLearnings — Pipeline Principal

Uso:
    from extract_learnings import extract_learnings

    # Al final de cada turno del agente Hermes:
    stats = await extract_learnings(
        transcript=conversation_text,
        session_id="hermes_20260711_1430"
    )
    print(f"Written {stats['written']} learnings to PDB")

Flujo:
    Transcript → Tom (Granite8B) extrae → Zalo (Qwen32B) valida → PDB ^System("learnings")

Inspirado en el Auto-Memory de Claude Code (extractMemories).
"""

import asyncio
from datetime import datetime, timezone

from extract_learnings.extractor import extract_facts_from_transcript
from extract_learnings.validator import validate_facts
from extract_learnings.writer import write_learnings_to_pdb


async def extract_learnings(
    transcript: str,
    session_id: str | None = None,
) -> dict[str, int]:
    """
    Pipeline completo: Extraer → Validar → Guardar.

    Args:
        transcript: Texto completo de la conversación (último turno o sesión completa)
        session_id: Identificador de sesión. Si es None, se autogenera.

    Returns:
        {
            extracted: int,              # Facts extraídos por Tom
            validated: int,              # Facts que pasaron a Zalo
            written: int,                # Facts escritos en PDB
            skipped_duplicates: int,     # Descartados por duplicados
            skipped_low_confidence: int, # Descartados por baja confianza (<4)
            errors: int,                 # Fallos de escritura
        }
    """
    if session_id is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        session_id = f"session_{ts}"

    empty_result = {
        "extracted": 0,
        "validated": 0,
        "written": 0,
        "skipped_duplicates": 0,
        "skipped_low_confidence": 0,
        "errors": 0,
    }

    # ── Paso 1+2: Extracción con Tom ──
    async with asyncio.timeout(3.0):  # Zalo: max 3s por extracción
        raw_facts = await extract_facts_from_transcript(transcript)
    extracted = len(raw_facts)

    if extracted == 0:
        return empty_result

    # ── Paso 3: Validación con Zalo ──
    validated_facts = await validate_facts(raw_facts)
    validated = len(validated_facts)

    # ── Paso 4: Escritura a PDB ──
    write_stats = await write_learnings_to_pdb(validated_facts, session_id)

    return {
        "extracted": extracted,
        "validated": validated,
        **write_stats,
    }


async def on_conversation_turn_end(transcript: str, session_id: str = "hermes"):
    """
    Hook ligero para integrar en el loop del agente Hermes.
    Se llama al final de cada turno, no bloquea al agente principal.

    Inspirado en handleStopHooks de Claude Code.
    """
    # Lanzar en background — mismo patrón que Claude Code (forked agent)
    asyncio.create_task(extract_learnings(transcript, session_id))
