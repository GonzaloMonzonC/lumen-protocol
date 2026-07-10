# extractLearnings — Plan de Implementación
## Adaptación del Auto-Memory de Claude Code al ecosistema PDB + Agentes

> **Fecha**: 2026-07-11
> **Target**: ~200 líneas Python
> **Destino**: PDB jerárquica bajo `^System("learnings")` vía pdb-edge-worker REST API

---

## 0. Algoritmo Exacto Extraído de Claude Code (Sección 2)

### Flujo de extractMemories original

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. TRIGGER: handleStopHooks()                                    │
│    Se ejecuta al final de CADA query loop (cada turno agente)    │
│                                                                   │
│ 2. SKIP CONDITION:                                               │
│    if main_agent_already_wrote_memories → skip                   │
│                                                                   │
│ 3. FORK:                                                         │
│    Forked agent (background, no bloquea al principal)             │
│    Comparte prompt cache prefix (coste ~0 en tokens)             │
│                                                                   │
│ 4. TOOLSET RESTRINGIDO:                                          │
│    ✅ Read/Grep/Glob (irrestricto)                                │
│    ✅ Bash (read-only)                                            │
│    ✅ Edit/Write (SOLO en memory directory)                       │
│    ❌ Todo lo demás denegado                                     │
│                                                                   │
│ 5. CLASIFICACIÓN (4 tipos, desde memoryTypes.ts):                 │
│    ┌───────────┬──────────────────────────────────────┬────────┐ │
│    │ user      │ Rol, goals, preferencias, knowledge   │ Privado│ │
│    │ feedback  │ Correcciones Y confirmaciones          │ Mixto  │ │
│    │ project   │ Ongoing work, deadlines, iniciativas   │ Team   │ │
│    │ reference │ URLs, APIs, docs externas              │ Team   │ │
│    └───────────┴──────────────────────────────────────┴────────┘ │
│                                                                   │
│ 6. FRONTMATTER YAML (formato de cada memory):                    │
│    ---                                                            │
│    name: Short descriptive title                                  │
│    description: One-line summary                                  │
│    type: user|feedback|project|reference                          │
│    ---                                                            │
│    Body content here — the actual knowledge                       │
│                                                                   │
│ 7. FILTRO RÍGIDO — QUÉ SE GUARDA / QUÉ NO:                       │
│    ✅ GUARDA:                                                     │
│       • User preferences, coding style, tech stack choices        │
│       • Corrections ("actually, use tabs not spaces")             │
│       • Project context ("we're migrating React→Svelte")          │
│       • External references ("staging API at https://...")        │
│       • Workflow preferences ("always run tests before commit")   │
│    ❌ NO GUARDA:                                                  │
│       • Code patterns, conventions, architecture, file paths      │
│       • Git history, recent changes, who-changed-what             │
│       • Debugging solutions o fix recipes                         │
│       • Contenido ya documentado en CLAUDE.md                     │
│       • Ephemeral task details: in-progress work, temp state      │
│                                                                   │
│ 8. INYECCIÓN:                                                    │
│    Next session → system prompt incluye MEMORY.md index            │
│    Debajo del DYNAMIC_BOUNDARY (cambia por sesión)                │
│                                                                   │
│ FILOSOFÍA: Memories capture knowledge about USER + PROJECT,       │
│ NO technical details que se pueden redescubrir leyendo archivos.  │
└─────────────────────────────────────────────────────────────────┘
```

### Lo que NO es solo un extractor: es un sistema completo con 4 capas

| Capa | Original (Claude Code) | Nuestra adaptación |
|------|----------------------|-------------------|
| **Extraction** | Auto-Memory (end of loop) | Tom (Granite8B) + prompt template |
| **Validation** | Implícita (mismo agente) | Zalo (Qwen32B) con scoring 1-10 |
| **Storage** | Markdown files en ~/.claude/memory/ | PDB `^System("learnings")` vía edge-worker |
| **Consolidation** | Auto-Dream (24h / 5 sesiones) | Futuro: fase 2 |

---

## 1. Adaptación a PDB Jerárquica con ^System("learnings")

### Estructura de datos en PDB

```
^System("learnings")
├── aprendizaje_001:
│   {
│     "hecho": "User prefers tabs over spaces for indentation",
│     "confianza": 9,
│     "tipo": "user",
│     "fuente": "session_20260711_1430_agent_hermes",
│     "tags": ["coding-style", "indentation", "preferences"],
│     "timestamp": "2026-07-11T14:35:22Z",
│     "validado_por": "zalo",
│     "extraido_por": "tom",
│     "raw_context": "En el turno 47 el usuario dijo: 'en este proyecto usamos tabs'"
│   }
├── aprendizaje_002:
│   {
│     "hecho": "Staging API hosted at https://api-staging.example.com",
│     "confianza": 8,
│     "tipo": "reference",
│     ...
│   }
```

### Ventajas sobre el modelo Claude Code (markdown files)

| Markdown files (original) | PDB `^System("learnings")` |
|--------------------------|---------------------------|
| Búsqueda: grep manual | Consultas por tags, tipo, confianza |
| Deduplicación: ausente | Query previa + fuzzy match |
| Consistencia: archivos sueltos | Jerarquía unificada bajo un namespace |
| Confianza: no existe | Score numérico 1-10 |
| Multi-agente: un solo escritor | Pipeline Tom→Zalo con roles claros |
| Syncing: team-memory manual | REST API unificada, multi-tenant |
| Auditoría: no hay | raw_context + timestamps + agentes |

### Claves PDB a usar

```
^System("learnings")          → namespace raíz
^System("learnings", id)      → aprendizaje individual (JSON)
^System("learnings_index")    → índice compacto tipo MEMORY.md (≤200 líneas)
^System("learnings_stats")    → contadores: {total, por_tipo, avg_confianza}
```

---

## 2. Plan de Implementación — 5 Pasos Concretos

### ✅ PASO 1: Prompt Template para Tom (el extractor)
**Archivo**: `extract_learnings/prompts.py`
**Líneas**: ~40

Crear el prompt system que Tom usa para extraer hechos. Debe codificar las reglas
QUÉ-SÍ / QUÉ-NO de Claude Code exactamente:

```python
EXTRACTION_SYSTEM_PROMPT = """You are a knowledge extraction agent. Your ONLY job is to extract
actionable, durable facts from a conversation transcript. You do NOT extract code patterns,
file paths, debugging solutions, or anything already documented elsewhere.

RULES — Extract ONLY if ALL of these are true:
1. The fact is about the USER (preferences, role, goals, knowledge level) OR the PROJECT
   (ongoing work, deadlines, initiatives, tech stack choices, external references)
2. The fact is LIKELY TO BE USEFUL in future sessions (>1 week from now)
3. The fact is NOT already documented in project files (CLAUDE.md, README, etc.)
4. The fact is NOT an ephemeral task detail (in-progress work, temporary state)
5. The fact is NOT a code pattern, convention, architecture note, or file path
6. The fact is NOT a debugging solution, git history, or recent change

CLASSIFY each fact into exactly one type:
- "user": User's role, goals, preferences, knowledge level
- "feedback": Corrections or confirmations of approach
- "project": Ongoing work, goals, deadlines, initiatives
- "reference": Pointers to external systems (URLs, APIs, docs)

OUTPUT: Return ONLY a JSON array. Each element:
{
  "hecho": "<one concise sentence capturing the knowledge>",
  "tipo": "user|feedback|project|reference",
  "tags": ["tag1", "tag2"],
  "raw_context": "<the exact sentence(s) from the transcript that support this>"
}

If nothing extractable: return []
"""
```

**Prompt de usuario** (lo que Tom recibe):
```python
EXTRACTION_USER_TEMPLATE = """
Conversation transcript:
{transcript}

Extract durable facts from this conversation. Apply the rules strictly.
Return valid JSON array only.
"""
```

---

### ✅ PASO 2: Llamada a Tom + Parseo de Resultados
**Archivo**: `extract_learnings/extractor.py`
**Líneas**: ~50

```python
import json
from typing import Any

# Asumiendo que Tom está expuesto vía MCP o HTTP
# from mcp_clients import tom_extract

async def extract_facts_from_transcript(transcript: str) -> list[dict[str, Any]]:
    """
    Llama a Tom (Granite8B) para extraer hechos del transcript.
    Retorna lista de facts en bruto: [{hecho, tipo, tags, raw_context}, ...]
    """
    # Tom usa mcp_tom_tom_extract (extracción estructurada JSON)
    # schema: array of {hecho, tipo, tags, raw_context}
    schema_desc = (
        "array of objects with keys: hecho (string, one-sentence fact), "
        "tipo (one of: user, feedback, project, reference), "
        "tags (array of strings), "
        "raw_context (string, exact transcript excerpt)"
    )

    # Llamada a Tom vía MCP
    raw = await tom_extract(text=transcript, schema=schema_desc)

    # Parseo robusto: Tom puede devolver JSON envuelto en markdown
    facts = _parse_tom_json(raw)

    # Validación estructural
    valid_facts = []
    for f in facts:
        if not isinstance(f, dict):
            continue
        if "hecho" not in f or not f["hecho"].strip():
            continue
        if f.get("tipo") not in ("user", "feedback", "project", "reference"):
            f["tipo"] = "project"  # default fallback
        if "tags" not in f:
            f["tags"] = []
        if "raw_context" not in f:
            f["raw_context"] = ""
        valid_facts.append(f)

    return valid_facts


def _parse_tom_json(raw: str) -> list[dict]:
    """Tom a veces envuelve JSON en ```json ... ```. Parseo robusto."""
    raw = raw.strip()
    if raw.startswith("```"):
        # Extraer contenido del code block
        lines = raw.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        raw = "\n".join(lines)
    return json.loads(raw)
```

---

### ✅ PASO 3: Validación con Zalo (Qwen32B) + Confidence Scoring
**Archivo**: `extract_learnings/validator.py`
**Líneas**: ~45

```python
from typing import Any

# Asumiendo Zalo vía MCP o HTTP
# from mcp_clients import zalo_chat

VALIDATION_PROMPT = """You are a knowledge quality validator. Rate each fact on a scale 1-10:

SCORING GUIDE:
1-3: False, misleading, hallucinated, or contradicts known facts
4-6: Possibly true but vague, lacks specificity, or low utility
7-8: Likely true and useful, but could be more precise
9-10: Clearly true, highly specific, and will be valuable in future sessions

For each fact, determine:
- confianza (1-10): how confident are you this is correct AND useful?
- is_duplicate (true/false): is this knowledge already captured?
- razon: brief justification

Output: JSON array with same order as input, each element:
{"confianza": 8, "is_duplicate": false, "razon": "Clearly stated by user, high utility"}
"""


async def validate_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Zalo valida cada hecho del batch. Añade confianza y flag is_duplicate.
    Retorna facts enriquecidos con metadata de validación.
    """
    if not facts:
        return []

    # Formatear facts para Zalo
    facts_text = "\n\n".join(
        f"FACT {i+1}:\n"
        f"  hecho: {f['hecho']}\n"
        f"  tipo: {f['tipo']}\n"
        f"  tags: {f.get('tags', [])}\n"
        f"  context: {f.get('raw_context', '')[:200]}"
        for i, f in enumerate(facts)
    )

    # Prompt a Zalo
    full_prompt = f"{VALIDATION_PROMPT}\n\nFACTS TO VALIDATE:\n{facts_text}"

    # Llamada a Zalo vía MCP
    response = await zalo_chat(mensaje=full_prompt)

    # Parsear respuesta
    try:
        validations = _parse_zalo_json(response)
    except Exception:
        # Fallback: confianza media si Zalo no puede parsear
        validations = [{"confianza": 5, "is_duplicate": False, "razon": "validation_failed"}
                       for _ in facts]

    # Merge: añadir confianza a cada fact
    for i, f in enumerate(facts):
        if i < len(validations):
            f["confianza"] = validations[i].get("confianza", 5)
            f["is_duplicate"] = validations[i].get("is_duplicate", False)
            f["validacion_razon"] = validations[i].get("razon", "")
        else:
            f["confianza"] = 5
            f["is_duplicate"] = False
            f["validacion_razon"] = ""

    return facts


def _parse_zalo_json(raw: str) -> list[dict]:
    """Parseo robusto igual que Tom."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        raw = "\n".join(lines)
    return json.loads(raw)
```

---

### ✅ PASO 4: Escritura en PDB vía pdb-edge-worker
**Archivo**: `extract_learnings/writer.py`
**Líneas**: ~40

```python
import json
import uuid
from datetime import datetime, timezone
from typing import Any
import httpx  # o requests

PDB_EDGE_WORKER_URL = "http://localhost:8787"  # Ajustar a CF D1 real
LEARNINGS_NAMESPACE = "learnings"


async def write_learnings_to_pdb(
    facts: list[dict[str, Any]],
    session_id: str,
) -> dict[str, Any]:
    """
    Escribe facts validados en PDB bajo ^System("learnings").
    Cada fact se convierte en un registro con metadata completo.

    Retorna: {written: N, skipped_duplicates: N, skipped_low_confidence: N}
    """
    stats = {"written": 0, "skipped_duplicates": 0, "skipped_low_confidence": 0}
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    async with httpx.AsyncClient(timeout=30) as client:
        for fact in facts:
            # Filtrar duplicados y baja confianza
            if fact.get("is_duplicate"):
                stats["skipped_duplicates"] += 1
                continue
            if fact.get("confianza", 5) < 4:
                stats["skipped_low_confidence"] += 1
                continue

            learning_id = f"learning_{uuid.uuid4().hex[:12]}"
            record = {
                "hecho": fact["hecho"],
                "confianza": fact.get("confianza", 5),
                "tipo": fact.get("tipo", "project"),
                "fuente": session_id,
                "tags": fact.get("tags", []),
                "timestamp": now_iso,
                "validado_por": "zalo",
                "extraido_por": "tom",
                "raw_context": fact.get("raw_context", ""),
            }

            # POST /v1/set/System/learnings/learning_xxx
            payload = {
                "key": f"{LEARNINGS_NAMESPACE}/{learning_id}",
                "value": json.dumps(record),
            }

            resp = await client.post(
                f"{PDB_EDGE_WORKER_URL}/v1/set/System",
                json=payload,
            )

            if resp.status_code in (200, 201):
                stats["written"] += 1
            else:
                # Log warning pero no detener el batch
                print(f"[WARN] PDB write failed for {learning_id}: {resp.status_code}")

    return stats
```

---

### ✅ PASO 5: Orquestador Principal + Hook de Integración
**Archivo**: `extract_learnings/orchestrator.py`
**Líneas**: ~35

```python
"""
extractLearnings — Pipeline Principal

Uso:
    from extract_learnings.orchestrator import extract_learnings

    # Al final de cada turno del agente Hermes:
    stats = await extract_learnings(transcript=conversation_text, session_id="hermes_20260711_1430")
    print(f"Extracted {stats['written']} learnings to PDB")
"""

import asyncio
from datetime import datetime, timezone
from extract_learnings.extractor import extract_facts_from_transcript
from extract_learnings.validator import validate_facts
from extract_learnings.writer import write_learnings_to_pdb


async def extract_learnings(
    transcript: str,
    session_id: str | None = None,
) -> dict:
    """
    Pipeline completo: Extraer → Validar → Guardar.

    Args:
        transcript: Texto completo de la conversación
        session_id: Identificador de sesión (default: autogenerado)

    Returns:
        {extracted, validated, written, skipped_duplicates, skipped_low_confidence}
    """
    if session_id is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        session_id = f"session_{ts}"

    # 1. Extraer hechos con Tom (Granite8B)
    raw_facts = await extract_facts_from_transcript(transcript)
    extracted = len(raw_facts)

    if extracted == 0:
        return {"extracted": 0, "validated": 0, "written": 0,
                "skipped_duplicates": 0, "skipped_low_confidence": 0}

    # 2. Validar con Zalo (Qwen32B)
    validated_facts = await validate_facts(raw_facts)
    validated = len(validated_facts)

    # 3. Escribir a PDB
    write_stats = await write_learnings_to_pdb(validated_facts, session_id)

    return {
        "extracted": extracted,
        "validated": validated,
        **write_stats,
    }


# ─── Hook para integrar en el agente Hermes ───

async def on_conversation_turn_end(transcript: str, session_id: str):
    """
    Hook que se llama al final de cada turno del agente.
    Ejecuta la extracción en background (no bloqueante).
    """
    # No bloquear — lanzar en background (como Claude Code)
    asyncio.create_task(extract_learnings(transcript, session_id))
```

---

## 3. Estructura de Archivos Final

```
extract_learnings/
├── __init__.py            # Exporta extract_learnings()
├── orchestrator.py        # Pipeline principal (Paso 5) — 35 líneas
├── prompts.py             # Templates de prompt (Paso 1) — 40 líneas
├── extractor.py           # Llamada a Tom + parseo (Paso 2) — 50 líneas
├── validator.py           # Validación con Zalo (Paso 3) — 45 líneas
├── writer.py              # Escritura PDB via edge-worker (Paso 4) — 40 líneas
└── README.md              # Este documento
```

**Total estimado**: ~210 líneas Python (dentro del target de ~200).

---

## 4. Diagrama de Flujo

```
CONVERSACIÓN TERMINA (end of turn)
         │
         ▼
┌─────────────────────────────────────────┐
│ on_conversation_turn_end()              │
│ (background, no bloquea al agente)      │
└──────────────────┬──────────────────────┘
                   │
                   ▼
         ┌─────────────────┐
         │ PASO 1 + 2: Tom  │  Granite8B — ultra barato
         │ extract_facts()  │  Clasifica en {user,feedback,project,reference}
         └────────┬────────┘  Aplica reglas QUÉ-SÍ / QUÉ-NO de Claude Code
                  │
         ┌────────▼────────┐
         │ PASO 3: Zalo     │  Qwen32B — scoring inteligente
         │ validate_facts() │  Asigna confianza 1-10 + flag is_duplicate
         └────────┬────────┘
                  │
         ┌────────▼────────┐
         │ PASO 4: PDB      │  pdb-edge-worker REST API
         │ write_learnings()│  POST /v1/set/System {key:"learnings/...", value: JSON}
         └────────┬────────┘
                  │
         ┌────────▼────────┐
         │ ^System           │  PDB Jerárquica
         │  ("learnings")    │  Cada registro con: hecho, confianza, tipo, tags,
         │                   │  fuente, timestamp, agentes, raw_context
         └──────────────────┘
```

---

## 5. Métricas de Éxito

| Métrica | Target | Cómo medir |
|---------|--------|-----------|
| Precisión de extracción | ≥80% facts reales | Muestreo manual 50 facts |
| Recall (no perder facts importantes) | ≥70% de los facts que un humano anotaría | Ground truth set |
| Tiempo de pipeline | <3s por turno | Instrumentación |
| Ruido (facts irrelevantes) | <20% descartados por Zalo | Ratio validados/descartados |
| Confianza media post-Zalo | ≥7/10 | Avg de confianza en ^System("learnings_stats") |

---

## 6. Próximos Pasos (Fuera de este plan)

1. **Fase 2 — Consolidación (Auto-Dream)**: Cada 24h o 50 learnings, un proceso similar al auto-dream de Claude Code que consolide learnings duplicados, actualice el índice y haga pruning.

2. **Inyección en System Prompt**: Al inicio de cada sesión, Hermes debe leer `^System("learnings_index")` e inyectar los learnings más relevantes debajo del `DYNAMIC_BOUNDARY`.

3. **Relevancia contextual**: No inyectar TODOS los learnings — solo los que matchean tags del contexto actual (usa embedding search contra los tags).

---

## 7. Dependencias

```txt
httpx>=0.27.0     # HTTP async para pdb-edge-worker
# Tom y Zalo accedidos vía MCP tools (ya disponibles en Hermes)
```

---

## 8. Aclaraciones Clave del Análisis

1. **El secreto NO es la complejidad del algoritmo**, es el **prompt de clasificación**:
   - Claude Code codifica reglas muy estrictas sobre qué se guarda y qué no
   - La lista de exclusiones es tan importante como la de inclusiones
   - Sin esto, el sistema se llena de ruido (debugging recipes, file paths...)

2. **La pipeline de 2 agentes (Tom→Zalo) es una mejora** sobre Claude Code:
   - Claude Code tiene UN solo agente que extrae y valida implícitamente
   - Nosotros separamos: modelo barato (Granite) para extraer, modelo potente (Qwen) para validar
   - Esto da **confidence scoring explícito** que Claude Code no tiene

3. **^System("learnings") vs markdown files**:
   - PDB permite queries estructuradas (por tag, tipo, confianza, fecha)
   - No requiere un proceso separado de "dreaming" para indexar
   - El índice puede generarse on-demand desde queries PDB
