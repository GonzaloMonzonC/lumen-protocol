---
name: lumen-control
description: '👽 Panel de control interactivo para LUMEN — monitoriza, activa/desactiva, diagnostica la integración LUMEN en Hermes Agent. Todos los tools LUMEN se marcan con 👽 en chat.'
version: 1.1.0
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
| `lumen test` | Probar conectividad |
| `lumen benchmark` | Built-in vs LUMEN comparativa |
| `lumen savings` | Ver ahorro de wire estimado |

## Servidores disponibles

| Server | Tools | Wire | Killer Feature |
|--------|-------|------|----------------|
| `lumen_filesystem` | **9** | 32-70% | Multi-agente, bulk read, streaming chunks |
| `lumen_web` | 2 | 40-50% | 1 call, zero-deps, DuckDuckGo |
| `lumen_thinking` | **29** (sequential_thinking, thought_similarity, thought_contradiction, thought_summarize, thought_to_plan, thought_evaluate, thought_bridge, assume, list_assumptions, check_assumption, model_add, model_query, model_stats, model_map, model_remove, model_scan, context_preserve, context_check, work_start, work_block, work_done, work_log, context_estimate, session_init, session_list, pattern_record, pattern_match, decision_log, decision_list) | 60-80% | 🔥 Razonamiento externo, TF-IDF zero-deps, Assumption Tracker, Mental Model Builder, Context Decay Detector, Work Tracker, Context Estimator, Session Isolation, Pattern Memory, Decision Log | `lumen-protocol/implementations/mcp-servers/thinking/` |
| `lumen_filesystem_native` | 9 (same as filesystem) | **55-58%** | 🔥 **LUMEN binary nativo**: PROBE/ACK real, sin JSON-RPC wrapper, 55-58% wire savings (medido June 2026). MUX + STREAM_DATA habilitados. Usa `server_native.py`. | `lumen-protocol/implementations/mcp-servers/filesystem/` |

**40+9 tools total** (38 MCP JSON-RPC + 9 native + 4 plugin overrides).

Plugin `lumen-native-fs`: override transparente de 4 built-ins (read_file, write_file, search_files, patch).

## Estado completo

Cuando el usuario pregunte por el estado de LUMEN: lee `~/.hermes/config.yaml`, busca `mcp_lumen.enabled`, `mcp_servers.*.transport`, `mcp_servers.*.enabled`, y muestra el panel.

## Activar / Desactivar

```bash
hermes config set mcp_lumen.enabled true   # Activar
hermes config set mcp_lumen.enabled false  # Desactivar
```

## LUMEN Skills Index

All Lumen skills in Hermes (9 total):

| Skill | Category | Focus |
|-------|----------|-------|
| **lumen-control** (this) | lumen | Dashboard, benchmarks, superiority bar, troubleshooting |
| **lumen-cognitive-workflows** | lumen | 6 composable cognitive workflow patterns |
| **lumen-thinking-hermes-integration** | lumen | Hermes plugins, hooks, subagent usage |
| **lumen-cognitive-safety** | lumen | SAFE/UNSAFE taxonomy, 7-gate audit, regression tests |
| **lumen-thinking-server-dev** | lumen | STREAM_DATA, MUX channels, native server dev |
| **lumen-cognitive-state-sync** | lumen | Multi-agent shared mental models via MUX |
| **lumen-mcp-server** | lumen | Server templates, benchmarking, documentation |
| **lumen-mcp-server-pattern** | lumen | Proven patterns, shared_tools, security, session isolation |
| **lumen-server-development** | lumen | Canonical guide, PROBE handshake, pitfall checklist |

## Troubleshooting rápido

### "MCP server 'X' failed to connect"
1. Prueba el server manualmente: `python server.py`
2. Revisa logs: `~/AppData/Local/hermes/logs/mcp-stderr.log`
3. Verifica que el venv de Hermes tiene `lumen` instalado

### Deadlock en Windows
FIXED (18/06/2026). El deadlock de pipe ocurría en server y cliente.
Ver `references/windows-deadlock-fix.md`.

### MCP server marcado "unreachable" tras 4 fallos
Hermes deja de reintentar tras 4 fallos consecutivos (~8 segundos).
Para forzar la reconexión:
```bash
hermes config set mcp_servers.<server>.enabled false
hermes config set mcp_servers.<server>.enabled true
```
Luego `/reset`. Ver `references/mcp-retry-recovery.md`.

### Si todo falla
Desactiva LUMEN globalmente: `mcp_lumen.enabled: false`

## Pitfalls (quick reference)

- **`build_size()`**: returns total wire size (fixed June 2026). Call `build_size(len(payload))`.
- **`decompress_value()`**: returns dict, NOT bytes.
- **Windows pipes**: use `read(1)` for servers, threading+Queue for transports.
- **Windows charmap**: add `sys.stdout.reconfigure(encoding="utf-8")` to all servers.
- **Sandbox**: `execute_code` cannot use asyncio+binary pipes.
- **Honesty in benchmarks**: never claim features Hermes already has. Measure first.

### 29 tools registered but only 7 visible

**Symptom**: Hermes logs show `registered 29 tool(s)` but the agent only sees ~7 thinking tools. Calls to tools #8-29 route to `sequential_thinking` with `'thought'` error.

**Root cause**: Hermes prompt caching. If the session started before the server was fully configured (e.g. pre-UTF-8 fix), the cached system prompt only includes the subset of tools that were available at session start. `/reset` does NOT regenerate the prompt cache — it only resets the conversation.

**Fix**: Start a fresh session (`/new` in CLI, or restart Hermes). The prompt cache is built from scratch and all 29 tools will appear.

**Workaround** (if a fresh session isn't possible): split large MCP servers into smaller servers of ≤7 tools each. Hermes registers them as separate servers and exposes all tools without the caching issue.

**Detection**: `grep "registered.*tool" ~/AppData/Local/hermes/logs/agent.log` shows all tools are registered. If the count is correct but the agent can't use them, it's a prompt cache problem.

### Tool call routing errors

**Symptom**: calling `mcp_lumen_thinking_assume(statement='...')` returns `Tool error: 'thought'`. The call routes to `sequential_thinking` instead.

**Root cause**: the tool doesn't exist in the agent's cached tool list. Hermes routes to the closest available match.

**Fix**: verify with logs that the tool IS registered, then start a fresh session.

## Referencias avanzadas

- **Benchmarks**: `references/benchmark-2026-06-16.md`, `references/benchmarks.md`
- **Windows**: `references/windows-deadlock-fix.md`, `references/windows-encoding-fix.md`, `references/windows-pitfalls.md`
- **Integration**: `references/hermes-integration-patterns.md`, `references/native-vs-wrapper.md`
- **Safety**: `references/cognitive-safety.md`
- **Testing**: `references/game-based-testing.md`, `references/game-session-2026-06-18.md`
- **Recovery**: `references/mcp-retry-recovery.md`
- **Diagnostic**: `scripts/diagnostic.py`
