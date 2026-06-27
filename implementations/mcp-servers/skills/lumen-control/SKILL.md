---
name: lumen-control
description: Panel de control interactivo para LUMEN — monitoriza, activa/desactiva, diagnostica la integración LUMEN en Hermes Agent.
version: 1.0.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, mcp, control-panel, diagnostic]
---

# LUMEN Control Panel

Panel interactivo para gestionar la integración LUMEN en Hermes Agent.
Este skill te da control total sobre el transporte LUMEN para servidores MCP.

---

## Comandos rápidos

| Comando | Acción |
|---------|--------|
| `lumen status` | Estado completo de LUMEN |
| `lumen on` | Activar LUMEN globalmente |
| `lumen off` | Desactivar LUMEN globalmente |
| `lumen servers` | Listar servidores LUMEN |
| `lumen test` | Probar conectividad (10 tests, 6 categorías) |
| `lumen benchmark` | Built-in vs LUMEN comparativa |
| `lumen savings` | Ver ahorro de wire estimado |

## Servidores disponibles

| Server | Tools | Wire | Killer Feature | Repo |
|--------|-------|------|----------------|------|
| `lumen_filesystem` | **13** (read_file, read_files, write_file, search_files, search_with_context, stream_read, patch, list_directory, file_info, search_filename, find_duplicates, disk_usage, read_files) | 32-70% | Multi-agente, bulk read, streaming chunks | `lumen-protocol/implementations/mcp-servers/filesystem/` |
| `lumen_web` | 2 (web_search + web_extract unificados) | 40-50% | 1 call en vez de 2, zero-deps | `lumen-protocol/implementations/mcp-servers/web/` |
| `lumen_thinking` | **46** (sequential_thinking, chains, kanban, wiki, Q&A, patterns, decisions, model, objectives, cognitive tools...) | 60-80% | 🔥 Razonamiento externo, TF-IDF zero-deps, Assumption Tracker, Mental Model Builder, Work Tracker | `lumen-protocol/implementations/mcp-servers/thinking/` |
| **`lumen_pdb`** 🔥 | **40** (pdb_set/get/kill/order/data/merge, $LOCK, triggers, auto-indices ^IDX, global mapping, partitioning, M-Light eval/REPL, MVM, backup, batch_set, FTS, scratchpad) | 71% | 🧠 **MUMPS en SQLite** — $ORDER, triggers, ^GLOBAL mapping, M-Light evaluador, MVM procesos | `lumen-protocol/implementations/mcp-servers/pdb/` |

**106 tools total en 4 servidores.**
Ninguno en `cadencia/apps/` (que es para apps que dependen de infraestructura de Cadences).

PR en hermes-agent: [#47740](https://github.com/NousResearch/hermes-agent/pull/47740)

### Config completa para Hermes

```yaml
# ~/.hermes/config.yaml
mcp_lumen:
  enabled: true

mcp_servers:
  lumen_filesystem:
    command: "python"
    args: ["C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/mcp-servers/filesystem/server.py"]
    transport: lumen
    lumen_force_json_rpc: true

  lumen_web:
    command: "python"
    args: ["C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/mcp-servers/web/server.py"]
    transport: lumen
    lumen_force_json_rpc: true

  lumen_thinking:
    command: "python"
    args: ["C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/mcp-servers/thinking/server.py"]
    transport: lumen
    lumen_force_json_rpc: true

  lumen_pdb:
    command: "python"
    args: ["C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb/server.py"]
    transport: lumen
    lumen_force_json_rpc: true
```

## Benchmarks reales (18/06/2026)

Todos los benchmarks son secuenciales, misma máquina, mismo test data:

### Filesystem vs Hermes built-in

| Tool | Hermes Built-in | LUMEN MCP | Overhead | Wire Savings |
|------|----------------|-----------|----------|-------------|
| `read_file` (100L) | 0.16ms | 0.42ms | +0.26ms | 32-50% |
| `search_files` | 13.8ms | **2.2ms** ⚡ | -11.5ms | 50% |
| `list_directory` | 9.7ms | 12.7ms | +3.0ms | 23% |
| `write_file` | <1ms | 0.8ms | ~0ms | 36% |
| `patch` | 0.5ms | 9.5ms | +9.0ms | 29% |

### Thinking server (sin equivalente Hermes)

| Tool | Latency | Wire Savings | Nota |
|------|---------|-------------|------|
| `sequential_thinking` | 0.1ms/op | 60-80% | 30-thought chain: 4ms total |
| `thought_similarity` | <1ms | 50-70% | TF-IDF puro Python, zero deps |
| `thought_summarize` | 15ms (30 thoughts) | 55-75% | Clustering aglomerativo |
| `thought_to_plan` | <1ms | 50-70% | Markdown + JSON output |
| `thought_bridge` | <1ms | 40-60% | Cross-chain connections |

### LUMEN transport (wire puro)

| Operación | JSON-RPC | LUMEN | Ahorro |
|-----------|----------|-------|--------|
| `tools/list` (4 tools) | 1128 B | 581 B | **48%** |
| `tool call` (echo) | 118 B | 61 B | **48%** |
| `error response` | 169 B | 102 B | **40%** |
| `agent loop` (30 turnos) | 2669 B | 1334 B | **50%** |

**Overhead medio: +0.3ms/op** — imperceptible vs 500-5000ms del LLM.

---

## Superiority Bar (principio clave)

**No LUMEN-ifiques una tool de Hermes a menos que sea ESTRICTAMENTE SUPERIOR.**

El usuario (Gonzalo) estableció esta regla: "cualquier cosa q hagamos una tool q
ya exista en hermes, debemos ser muy superiores en todo sino no conviene no?"

Antes de añadir una tool al server LUMEN, verifica:
1. **Wire savings**: ¿≥30% en payloads típicos? (Estructura → sí, contenido → no)
2. **Features**: ¿hace algo que Hermes built-in NO puede hacer?
3. **Multi-agent**: ¿beneficia a escenarios con múltiples agentes?

**⚠️  HONESTIDAD EN CLAIMS**: Antes de afirmar que una feature es "exclusiva de LUMEN",
verifica que Hermes built-in NO la tenga. Ejemplo: Hermes `search_files` SÍ tiene
`context` y `output_mode` — no son exclusivos de LUMEN. La ventaja real de LUMEN
es velocidad (2.2ms vs 13.8ms) y multi-agente, no features inexistentes en Hermes.
El usuario corrigió este error en sesión del 18/06/2026.

Ejemplos:
- `web_search` → ❌ DESCARTADO. Mismo resultado, mismo backend, +0.5ms overhead.
  No es superior. La latencia de red (200-500ms) eclipsa cualquier ahorro de wire.
- `web_extract` → ⚠️ COMPLEMENTARIO, no sustituto. Hermes usa Firecrawl (calidad
  profesional, markdown limpio). LUMEN usa HTML parsing (stdlib, sin API key).
  LUMEN gana en: velocidad (183ms vs ~500ms), zero-deps, search+extract unificado.
  Hermes gana en: calidad de extracción. Usar LUMEN para búsquedas rápidas ligeras,
  Hermes para extracción de calidad profesional. Ver `references/web-extract-benchmark-2026-06-17.md`.
- `read_files` (bulk) → ✅ APROBADO. Hermes NO tiene lectura múltiple en una
  - `search_files` → ✅ APROBADO. Hermes built-in tarda 13.8ms, LUMEN tarda 2.2ms (6× más rápido). Hermes también tiene `context` y `output_mode` — la ventaja de LUMEN es velocidad y multi-agente, no features exclusivas.
  - `search_with_context` → ✅ APROBADO. Hermes tiene `context` en `search_files` pero LUMEN `search_with_context` ofrece mejor UX: marcador `>>>`, ±N líneas, y flujo dedicado para inspección de código.
- `list_directory` → ✅ APROBADO. 90% estructura, 23% wire savings. Hermes no
  tiene equivalente built-in (usa `search_files target=files`).
- `stream_read` → ✅ APROBADO. Paginación de archivos enormes en chunks.
  Hermes `read_file` tiene límite de 2000 líneas. Feature diferencial.
- `server_stats` → ✅ APROBADO. Health check + métricas de uso. Hermes no tiene.
- `sequential_thinking` → ✅ APROBADO. Razonamiento externo 80% estructura,
  60-80% wire savings. Hermes NO tiene equivalente. 0.1ms/thought, 34 tests.
- `thought_similarity` → ✅ APROBADO. TF-IDF cosine similarity en Python stdlib.
  Permite al LLM encontrar pensamientos relacionados sin repetirse.
- `thought_contradiction` → ✅ APROBADO. Detección de contradicciones vía
  sentiment heuristics + TF-IDF. El LLM corrige antes de ejecutar.
- `thought_summarize` → ✅ APROBADO. Clustering aglomerativo de pensamientos
  por tema. Resume cadenas largas para el contexto.
- `thought_to_plan` → ✅ APROBADO. Convierte cadena de razonamiento en plan
  accionable (markdown o JSON). Del pensamiento a la acción.
- `thought_evaluate` → ✅ APROBADO. Scoring de calidad de pensamiento
  (especificidad, accionabilidad, concreción). Feedback constructivo.
- `thought_bridge` → ✅ APROBADO. Conexiones cross-chain entre sesiones.
  El LLM aprende de razonamientos pasados.
- `assume` / `list_assumptions` / `check_assumption` → ✅ APROBADO. Assumption
  Tracker: registra asunciones explícitamente, las lista con filtros, y las marca
  como confirmadas/refutadas. Expande la percepción del agente sin reemplazar su
  juicio. PRINCIPIO DE SEGURIDAD COGNITIVA: herramientas que EXPANDEN percepción,
  NO que REEMPLAZAN juicio. Decision Journal y Confidence Tracker fueron
  DESCARTADOS por riesgo de sesgo (sobre-generalización, dogmatismo).
- `model_add` / `model_query` / `model_stats` / `model_map` / `model_remove` / `model_scan` →
  ✅ APROBADO. Mental Model Builder: grafo factual del proyecto (archivos,
  roles, dependencias). Puramente factual, sin opiniones. El agente construye
  un mapa vivo del proyecto y consulta dependencias e impacto de cambios.
  `model_scan` auto-descubre archivos en un directorio, adivina roles por
  nombre de archivo, y detecta imports de Python para construir dependencias.
- `context_preserve` / `context_check` → ✅ APROBADO. Context Decay Detector:
  preserva información crítica antes de que el contexto se compacte. Evalúa
  riesgo de pérdida (LOW/MEDIUM/HIGH) y sugiere acciones.
- `work_start` / `work_block` / `work_done` / `work_log` → ✅ APROBADO. Work
  Tracker: persistencia de tareas entre sesiones vía `.work_log.json`.
  Complementa el TODO list de Hermes (que es per-sesión). El agente retoma
  trabajo donde lo dejó tras un `/reset`. Puramente factual.
- `context_estimate` → ✅ APROBADO. Context Estimator: estimación heurística
  del % de contexto usado (basado en tool calls y tiempo de sesión). Sugiere
  externalizar cuando el riesgo es HIGH (>70%). No mide tokens reales —
  es una guía para ser proactivo.

---

## Estado completo

Cuando el usuario pregunte por el estado de LUMEN:

1. Lee `~/.hermes/config.yaml`
2. Busca: `mcp_lumen.enabled`, `mcp_servers.*.transport`, `mcp_servers.*.enabled`
3. Muestra el panel:

```
╔══════════════════════════════════════════════╗
║           ◆  LUMEN Control Panel  ◆         ║
╠══════════════════════════════════════════════╣
║                                              ║
║  Global LUMEN:  ● ON  / ○ OFF                ║
║                                              ║
║  Servers:                                    ║
║  ┌──────────────────────────────────────────┐║
║  │ lumen_filesystem  ● ONLINE  LUMEN ✅     │║
║  │   read_file, write_file, search, patch   │║
║  │   Wire savings: ~45%                     │║
║  │ lumen_web         ● ONLINE  LUMEN ✅     │║
║  │   web_search, web_extract                │║
║  │   Wire savings: ~45%                     │║
║  └──────────────────────────────────────────┘║
║                                              ║
║  Wire Savings (est.):                        ║
║  ████████████████████░░░░  45%               ║
║                                              ║
║  [On] [Off] [Test] [Servers] [Salir]         ║
╚══════════════════════════════════════════════╝
```

---

## Activar / Desactivar

### Activar LUMEN:
```bash
hermes config set mcp_lumen.enabled true
```
O editar `config.yaml`:
```yaml
mcp_lumen:
  enabled: true
```

Luego reiniciar sesión (`/reset`).

### Desactivar LUMEN:
```bash
hermes config set mcp_lumen.enabled false
```
O desde el chat:
```
/config set mcp_lumen.enabled false
```

---

## Servidores

### Listar servidores LUMEN configurados:
Revisar `mcp_servers` en `config.yaml`. Los que tengan `transport: lumen` usan el protocolo binario.

### Añadir un nuevo servidor LUMEN:
```yaml
mcp_servers:
  mi_server:
    command: "python"
    args: ["/ruta/al/server.py"]
    transport: lumen
    lumen_force_json_rpc: true  # si el server no habla LUMEN nativo
```

### Activar/desactivar un server específico:
```yaml
mcp_servers:
  lumen_filesystem:
    enabled: false  # desactiva solo este
```

---

## Diagnóstico

### Test de conectividad:
```bash
# Verifica que el server responde
server_path = r"C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/mcp-servers/filesystem/server.py"
# En otra terminal, enviar JSON-RPC de prueba
```

### Logs de MCP:
```bash
cat ~/AppData/Local/hermes/logs/mcp-stderr.log | tail -50
```

### Verificar que LUMEN package está instalado:
```bash
python -c "import lumen; print('LUMEN', lumen.__file__)"
```

---

## Métricas de ahorro

**IMPORTANTE: LUMEN comprime ESTRUCTURA JSON, no contenido de archivos.**
Los ahorros reales dependen del tipo de payload. Ver `references/benchmark-2026-06-16.md`
para resultados completos del benchmark exhaustivo (14 tests, 6 categorías).

| Operación | JSON | LUMEN | Ahorro | Nota |
|-----------|------|-------|--------|------|
| `tools/list` (4 tools) | 1128 B | 581 B | **48%** | Mucha estructura → alto ahorro |
| `tool call` (echo) | 118 B | 61 B | **48%** | Estructura domina |
| `error response` | 169 B | 102 B | **40%** | Claves JSON comprimibles |
| `agent loop` (30 turnos) | 2669 B | 1334 B | **50%** | Mejor caso: pura estructura |
| `read_file` (500 líneas) | 12584 B | 12029 B | **4%** | ⚠️ Contenido domina → bajo ahorro |

**Conclusión**: LUMEN brilla con operaciones ricas en estructura (tools/list,
schemas, errores, agent loops). Para `read_file`/`write_file`, el beneficio
NO está en el wire — está en multi-agente (N agentes → 1 server), streaming,
y seguridad (Macaroons).

---

## Pitfalls & Lecciones Aprendidas

### Benchmarking justo
- **No compares `read()` con `readline()`** en pipes de Windows: `read(N)` bloquea
  hasta EOF. Usa siempre `readline()` para JSON-RPC.
- **No midas wire savings comparando request vs response** — mide el response
  JSON-RPC completo vs su equivalente comprimido con LUMEN.
- **MCP stdio NO es thread-safe**: múltiples hilos escribiendo al mismo pipe
  stdin corrompen el framing JSON-RPC. Haz benchmarks secuenciales.

### Rendimiento real
- **Latencia LUMEN vs OS directo**: ~0.3ms extra por operación. Para 100
  ops/turno son ~25ms, imperceptible frente a 500-5000ms del LLM.
- **Wire savings reales**: 40-50% para operaciones con estructura (tools/list,
  schemas, errores). Solo 1-7% para operaciones con mucho contenido
  (read_file de archivos grandes).
- **El valor de LUMEN para filesystem NO está en la compresión** — está en
  multi-agente (N agentes comparten 1 server), streaming, Macaroons, y
  aislamiento de proceso.

### Windows-specific
- `subprocess.Popen.stdin.flush()` puede fallar con `OSError [Errno 22]` en
  Windows. Usar try/except.
- `asyncio` + `run_in_executor` con pipes puede colgar en el sandbox de
  `execute_code`. Para tests, usar `subprocess` directo + `readline()`.
- El `read(N)` de Python en pipes de Windows bloquea hasta EOF. Usar `readline()`.

### Configuración
- El `mcp_tool.py` en `AppData/Local/hermes/` es COPIA DISTINTA del repo git.
  Hay que sincronizar manualmente después de cambios.
- `lumen_force_json_rpc: true` es necesario cuando el server MCP no habla
  LUMEN nativo (solo JSON-RPC).

---

## Troubleshooting rápido

### "MCP server 'X' failed to connect"
1. Prueba el server manualmente: `python server.py`
2. Revisa logs: `~/AppData/Local/hermes/logs/mcp-stderr.log`
3. Verifica que el venv de Hermes tiene `lumen` instalado

### "LUMEN SDK not available"
```bash
pip install -e C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/python
```

### Deadlock en Windows (server no responde)
**🐛 ARREGLADO (18/06/2026).** El deadlock de pipe ocurría en DOS lados:
1. **Server**: `read_lumen_frame()` usaba `read(4096)`. Fix: `read(1)` byte a byte.
2. **Cliente (transport.py)**: `_wait_for_ack()` y `_read_lumen()` usaban `read(4096)` / `readline()`. Fix: `read(1)` byte a byte en ambos.

Si después del fix el server sigue colgando, reinstalar el paquete:
```bash
pip install -e C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/python
```
Ver `references/windows-pitfalls.md` §7.

### Si todo falla
Desactiva LUMEN globalmente:
```yaml
mcp_lumen:
  enabled: false
```

## Referencias avanzadas

- **[Hermes Integration Patterns](references/hermes-integration-patterns.md)** — `override=True`, `_LumenSession`, MCP filesystem server pattern, Phase 0 vs Phase 1 decision
- **[Windows Deadlock Fix](references/windows-deadlock-fix.md)** — Fix completo para el deadlock de pipes en Windows: `read(4096)/readline()` → `read(1)` en server + client transport
- **[Native vs Wrapper Architecture](references/native-vs-wrapper.md)** — Pattern A (JSON-RPC over LUMEN) vs Pattern B (LUMEN native binary). Includes `build_size` pitfall.
- **[Schema Audit Methodology](references/schema-audit.md)** — Cómo comparar tus schemas MCP con los built-in de Hermes. Errores encontrados y cómo evitarlos.
- **[Web Extract Benchmark](references/web-extract-benchmark-2026-06-17.md)** — LUMEN vs Hermes web_extract: cuándo usar cada uno
- **[Cognitive Safety](references/cognitive-safety.md)** — Principios para tools cognitivas seguras: expandir percepción, no reemplazar juicio. Decision Journal y Confidence Tracker DESCARTADOS.
- **[Game-Based Testing](references/game-based-testing.md)** — Metodología de diagnóstico con proyecto simulado y bugs intencionales.
- **[Diagnostic Script](scripts/diagnostic.py)** — chequeo de salud de LUMEN
- **[Game Session 2026-06-18](references/game-session-2026-06-18.md)** — bug hunt diagnosis: 7✅, 2🐛 found in LUMEN tools

## LUMEN Skills Index

All Lumen skills in Hermes (9 total):

| Skill | Category | Focus |
|-------|----------|-------|
| **lumen-control** (this) | lumen | Dashboard, benchmarks, superiority bar, troubleshooting |
| **[lumen-cognitive-workflows](lumen-cognitive-workflows)** | lumen | 5 composable cognitive workflow patterns |
| **[lumen-thinking-hermes-integration](lumen-thinking-hermes-integration)** | lumen | Hermes plugins, hooks, subagent usage |
| **[lumen-cognitive-safety](lumen-cognitive-safety)** | lumen | SAFE/UNSAFE taxonomy, 7-gate audit, regression tests |
| **[lumen-thinking-server-dev](lumen-thinking-server-dev)** | lumen | STREAM_DATA, MUX channels, native server dev |
| **[lumen-cognitive-state-sync](lumen-cognitive-state-sync)** | lumen | Multi-agent shared mental models via MUX |
| **lumen-mcp-server** | lumen | Server templates, benchmarking, documentation |
| **lumen-mcp-server-pattern** | lumen | Proven patterns, shared_tools, security, session isolation |
| **lumen-server-development** | lumen | Canonical guide, PROBE handshake, pitfall checklist |

**For detailed pitfall checklist**: see `lumen-server-development` — Frame building, decompression, FrameAssembler, Hyb128 strict mode, Windows pipe I/O, tool schemas, error handling, multi-agent.

## Pitfalls (quick reference)

- **`build_size()`**: now returns total wire size (fixed June 2026). Call `build_size(len(payload))` — no manual addition.
- **`decompress_value()`**: returns dict, NOT bytes. Don't `json.loads()` it.
- **Windows pipes**: `sys.stdin.buffer.read(N)` blocks until N bytes or EOF. For servers, use `read(1)` byte-by-byte. For high-throughput transports, use threading + `asyncio.Queue` pattern. See `lumen-server-development`.
- **Sandbox**: `execute_code` cannot use asyncio+binary pipes. Use `terminal` or standalone scripts.
- **Schema compatibility**: mirror Hermes built-in schemas exactly. See `references/schema-audit.md`.
- **Path handling**: Windows backslashes need `os.path.normpath()`. See `references/game-session-2026-06-18.md`.
- **Config sync**: `mcp_tool.py` in `AppData/` is a COPY of the git repo — sync manually after changes.
- **Deadlock (Windows)**: FIXED June 2026. `read(4096)` → `read(1)` in server + client transport.
- **Honesty in benchmarks**: never claim features Hermes already has. Measure before claiming.
