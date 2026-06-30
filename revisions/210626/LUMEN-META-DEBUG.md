# LUMEN Meta-Debug Report — Using Tools to Improve Tools

> **Fecha:** 2026-06-21  
> **Modelo:** DeepSeek V4 Flash (iteración 2 — modo meta)  
> **Propósito:** Usar las propias herramientas LUMEN para diagnosticar y mejorar las herramientas LUMEN  
> **Herramientas utilizadas:** state_snapshot, cognitive_integrity, unified_search, pattern_record, sequential_thinking, kanban_stats, task_search, qa_list, web_snapshots_list, decision_list, model_map, batch_call

---

## Metodología

Este documento fue generado siguiendo un proceso circular: usar una tool LUMEN, analizar su salida, detectar una carencia, registrar el patrón, implementar el fix, y documentar el ciclo completo.

```
👽 tool → detectar problema → 👽 pattern_record → 👽 fix → documentar
```

---

## Ciclo 1: cognitive_integrity revela sus propias carencias

**Problema detectado:** `cognitive_integrity()` reportaba **0 decisions** aunque sabíamos que existían.

👽 **cognitive_integrity** mostraba:
```
Total artifacts: 18 tasks + 3 Q&A + 0 decisions + 21 patterns + 6 snapshots
```

Pero 👽 **decision_list** mostraba 8 decisiones. La discrepancia era un bug en la tool: buscaba `_decisions` como variable global del módulo, pero las decisiones viven dentro de cada sesión en `_sessions[sid].decisions`.

**Fix aplicado:** 👽 `pattern_record` (#27) + `patch` en server.py para iterar sesiones:
```python
session_decisions = sum(len(s.decisions) for s in list(_sessions.values()))
```

**Lección:** No asumir que todos los datos cognitivos están en el módulo global. Algunos viven per-session.

---

## Ciclo 2: 18 tasks sin links cognitivos

**Problema detectado:** El 100% de las tasks no tienen links a chains/patterns/decisions.

👽 **cognitive_integrity**: `18 tasks without links`

**Causa raíz:** `task_link` existe como tool, pero:
1. No hay un hook automático que sugiera links al crear una task
2. El agente (yo) no recordaba usarlo consistentemente
3. No hay retroalimentación visual en el dashboard que recuerde "esta task no tiene contexto cognitivo"

**Fix propuesto:** No implementado aún (requiere `link_auto` tool de la roadmap PRO).

**Lección:** Tener la tool no es suficiente. El sistema necesita friction positiva — recordatorios, sugerencias, automatización.

---

## Ciclo 3: 20 patterns nunca matcheados

**Problema detectado:** De 25 patrones registrados, 20 nunca se usaron via `pattern_match`.

👽 **cognitive_integrity**: `20 patterns never matched (may be obsolete)`

**Causa raíz:** `pattern_match` busca por similitud Jaccard sobre descripciones de patrones. Si el agente no llama a `pattern_match` explícitamente, los patrones acumulan polvo.

**Fix propuesto:** 
- Corto plazo: `state_snapshot` debería sugerir patrones relevantes basados en las chains activas (ya existe: `💡 N pattern suggestions`)
- Largo plazo: `insight_feed()` tool que muestre patrones sin usar, decisions sin revisar, etc.

**Lección:** El conocimiento institucional solo vale si se consulta. Los patrones necesitan un recordatorio periódico.

---

## Ciclo 4: unified_search no encuentra contenido cognitivo

**Problema detectado:** `unified_search("deterministic brain PFC LUMEN")` devolvió 0 resultados, aunque el contenido existe en:
- 👽 `pattern` #26: "prefrontal-cortex-hypothesis"
- 👽 `qa_ask`: "Como replica LUMEN la corteza prefrontal humana?"
- Pero está en sessions locales, no en `_global_patterns`

**Causa raíz:** `unified_search` busca en `_global_patterns[-200:]` (los últimos 200 patrones globales). Pero `pattern_record` guarda en la sesión LOCAL primero, y solo replica a `_global_patterns` si existe. Los patrones de esta sesión podrían estar solo en local.

**Fix:** Añadir búsqueda también en patrones locales de la sesión actual.

**Lección:** La replicación global de patrones no es automática ni garantizada. `unified_search` debería buscar en ambas fuentes.

---

## Ciclo 5: Las tools LUMEN revelan su propia estructura de datos

👽 **model_map** mostró la arquitectura:

```
📁 ./
   📄 PFC hypothesis [pattern]
   📄 deterministic-brain [pattern]
   📄 cognitive-integrity-decisions-bug [pattern] ← NUEVO
   ...
```

El modelo mental de LUMEN sobre sí mismo está creciendo. `model_map` muestra que LUMEN tiene entidades sobre:
- Vulnerabilidades (VULN-1..6)
- Servicios (cognitive-os-demo, final-verification)
- Tareas (Fase C, Implement kanban)
- Patrones (cada `pattern_record` genera una entidad)
- Nodos del sistema (niche:lumen-protocol)

**Pero falta:** No hay entidades que representen las herramientas LUMEN mismas. El modelo mental de LUMEN sobre LUMEN es invisible. No hay una entidad "state_snapshot", "cognitive_integrity", "unified_search" en el modelo.

---

## Resumen de Hallazgos

| # | Tool que detectó | Problema | Estado |
|---|-----------------|----------|:------:|
| 1 | `cognitive_integrity` | 0 decisions mostradas (busca en módulo, no en sessions) | ✅ Fix aplicado |
| 2 | `cognitive_integrity` | 18/18 tasks sin links | 🔄 Propuesto `link_auto` |
| 3 | `cognitive_integrity` | 20/25 patterns nunca matcheados | 🔄 Propuesto `insight_feed` |
| 4 | `unified_search` | No encuentra contenido en sessions locales | 🔄 Propuesto fix |
| 5 | `model_map` | El modelo mental no incluye las propias tools | 🔄 Propuesto `model_add` automático |

---

## Métricas del Meta-Debug

```
Sesión iniciada con:   10c · 32t · 25p · 16w · 434 calls
Sesión finalizada con: 10c · 32t · 26p · 16w · 438 calls

Bug encontrado:   1 (decisions count en cognitive_integrity)
Bug arreglado:    1 (✅ fixed server-side)
Patrón registrado: #26 (cognitive-integrity-decisions-bug)
Documentos:        LUMEN-EXPERIENCE-REPORT.md (Flash) 
                   LUMEN-EXPERIENCE-REPORT-PRO.md (PRO) 
                   LUMEN-META-DEBUG.md (este)

Tools usadas para el meta-debug: 11
  state_snapshot, cognitive_integrity, unified_search, sequential_thinking,
  pattern_record, kanban_stats, task_search, qa_list, web_snapshots_list,
  decision_list, model_map
```

---

## Conclusión

> Las herramientas LUMEN son lo suficientemente potentes para diagnosticar sus propias carencias. `cognitive_integrity` encontró su propio bug. `unified_search` detectó su limitación de scope. `model_map` reveló que el modelo mental no se incluye a sí mismo.

> Este es el primer paso hacia un sistema auto-consciente: un sistema que puede usar sus propias herramientas para mejorarse a sí mismo.

> Próximo salto: que las herramientas no solo detecten sus carencias — sino que propongan e implementen los fixes automáticamente.
