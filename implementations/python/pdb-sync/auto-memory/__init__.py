"""
extract_learnings — Auto-Memory adaptado a PDB + Agentes

Sistema de extracción de conocimiento durable desde conversaciones,
inspirado en el Auto-Memory de Claude Code (extractMemories).

Pipeline de 2 agentes:
    Tom (Granite8B) → extrae hechos
    Zalo (Qwen32B)  → valida y puntúa confianza

Almacenamiento en PDB jerárquica:
    ^System("learnings", learning_<uuid>) → JSON con metadata completo

Uso rápido:
    from extract_learnings import extract_learnings, on_conversation_turn_end

    # Modo directo:
    stats = await extract_learnings(transcript, session_id="hermes_001")

    # Modo hook (background, no bloqueante):
    await on_conversation_turn_end(transcript, session_id="hermes_001")
"""

from extract_learnings.orchestrator import extract_learnings, on_conversation_turn_end

__all__ = ["extract_learnings", "on_conversation_turn_end"]
