# LUMEN Cognitive OS — Arquitectura Completa

> **Versión**: 3.0 | **Fecha**: 2026-06-19
> **Transport**: LUMEN Level 2 — Shared Memory (mmap ring buffers, zero-copy)
> **Tools**: 46 thinking + 13 filesystem + 2 web + 17 PDB + 5 objective loop = **83 tools total**
> **Plugin**: `lumen-shm-bridge` (Hermes Agent)

---

## 🧠 Visión General

LUMEN Cognitive OS transforma Hermes Agent de un "chatbot con herramientas" a un **sistema operativo cognitivo multi-agente** con:

1. **Wiki Mental** — conocimiento persistente editable vía dashboard
2. **Cross-Session Awareness** — agentes conscientes entre sí, mensajería, detección de colisiones
3. **Institutional Memory** — patrones globales, decisiones, assumptions que sobreviven sesiones
4. **Zero-Copy Transport** — SHM Level 2, 0 kernel copies, latencia sub-ms

---

## ⚡ SHM Transport — La Base de Todo

LUMEN reemplaza JSON-RPC stdio con **Level 2 Shared Memory (mmap ring buffers)**:

| Métrica | JSON-RPC (Hermes built-in) | LUMEN SHM | Ventaja |
|---------|---------------------------|-----------|---------|
| **Latencia por tool call** | 30-43ms | 0.3-4.2ms | **9× más rápido** |
| **Throughput thinking** | ~100 calls/sec | **3,407 calls/sec** | **34× mayor** |
| **Throughput filesystem** | ~100 calls/sec | **525 calls/sec** | **5× mayor** |
| **Kernel copies** | 2 por mensaje | **0** (zero-copy mmap) | ∞ |
| **Wire savings** | 0% | **5-59%** (avg 29%) | Menos tokens |
| **Errores** | — | **0 en 530+ calls** | 100% reliability |

### Cómo funciona

```
Hermes Agent                    LUMEN MCP Server
    │                                │
    │  read_file("doc.txt")         │
    ├──► SHM ring buffer ──────────►│  ① Write request to ring
    │      (zero-copy mmap)         │
    │                               │  ② OS maps file via mmap
    │      ◄── SHM ring buffer ────┤
    │          (zero-copy mmap)     │  ③ Write response to ring
    │                               │
    └── Result displayed ───────────┘  ④ Agent reads from ring

    Total kernel copies: 0
    Total memcpy operations: 1 (ring → agent buffer)
```

**Sin SHM (Hermes built-in)**:
```
Hermes Agent ──► kernel ──► bash ──► kernel ──► file
                                     (2 copies + fork + exec)
```

---

## 🗺️ Arquitectura de 46 Tools

### Thinking Server — 46 tools

| Subsistema | Tools | Propósito |
|------------|-------|-----------|
| **Reasoning Chain Engine** (9) | `sequential_thinking`, `thought_similarity`, `thought_contradiction`, `thought_summarize`, `thought_to_plan`, `thought_evaluate`, `thought_bridge` | Razonamiento estructurado externo |
| **Assumption Tracker** (3) | `assume`, `list_assumptions`, `check_assumption` | Superficie de premisas ocultas |
| **Mental Model Builder** (6) | `model_add`, `model_query`, `model_stats`, `model_map`, `model_remove`, `model_scan` | Grafo de conocimiento persistente |
| **Context Preservation** (3) | `context_preserve`, `context_check`, `context_estimate` | Anclaje cross-session |
| **Work Tracking** (4) | `work_start`, `work_block`, `work_done`, `work_log` | Tareas multi-sesión |
| **Session Management** (2) | `session_init`, `session_list` | Aislamiento multi-agente |
| **Pattern Memory** (2) | `pattern_record`, `pattern_match` | Memoria institucional + global store |
| **Decision Log** (2) | `decision_log`, `decision_list` | Decisiones con triggers de revisita |
| **Kanban Cognitive** (7) | `niche_create`, `niche_list`, `niche_update`, `task_create`, `task_move`, `task_list`, `task_link` | Organización por nichos cognitivos |
| **Agent Loop** (5) | `objective_create`, `objective_judge`, `objective_plan`, `objective_status`, `objective_task_done` | Mini-agentes autónomos de objetivos |
| **Web Snapshots** (2) | `web_snapshot`, `web_snapshots_list` | Captura persistente de páginas web |
| **Q&A** (3) | `qa_ask`, `qa_list`, `qa_link` | Pares pregunta-respuesta persistentes |
| **Token-Efficient** (5) | `state_snapshot`, `thought_compress`, `chain_diff`, `tool_cache`, `batch_call` | Operaciones con 90-95% menos tokens |
| **Cross-Session Comms** (3) | `agent_message`, `agent_inbox`, `collision_check` | 🆕 Mensajería entre agentes + detección de conflictos |

### Filesystem Server — 13 tools

`read_file`, `write_file`, `search_files`, `patch`, `list_directory`, `read_files` (bulk), `search_with_context`, `stream_read`, `server_stats`, `file_info`, `disk_usage`, `search_filename`, `find_duplicates`

### Web Server — 2 tools

`web_search`, `web_extract`

### PDB Server — 15 tools

MUMPS-compatible process database with SQLite backend. Full CRUD: pdb_get, pdb_set, pdb_kill, pdb_order, pdb_data, pdb_incr, pdb_merge, pdb_query, pdb_schema, pdb_fts_search, pdb_backup, pdb_batch_set.

---

## 🔗 Cross-Session Cognition

### Agentes que se comunican

```python
# Agente A (default)
agent_message(to_session="agent-b", content="Revisé el PR, ¿tienes objeciones?")

# Agente B (session de agent-b)
agent_inbox()
# → 📨 default: "Revisé el PR, ¿tienes objeciones?"

# Agente B responde
agent_message(to_session="default", content="Ninguna objeción. Merge approved.")
```

### Detección de colisiones

```python
# Agente A toca un archivo model_add con deps=["repo-file-x"]
# Agente B toca el mismo archivo
collision_check()
# → ⚠️ repo-file-x: default, agent-b
# 💡 Use agent_message to coordinate
```

### Memoria institucional global

```python
# Agente A registra un patrón
pattern_record(pattern_name="null-check-async", description="Bug en callbacks...")

# Días después, Agente B encuentra el mismo bug
pattern_match(description="null pointer in async callback")
# → 42% match: null-check-async → fix: "add null guard before await"
```

Los patrones se almacenan en `_global_patterns` (compartido entre todas las sesiones) y se persisten en disco cada 10 tool calls.

---

## 📊 Benchmarks Completos

### Thinking Server (29 tools originales)

| Métrica | Valor |
|---------|-------|
| Total calls | 250 |
| Errores | 0 |
| Throughput | **3,407 calls/sec** |
| Latencia avg | **0.29ms** |
| Latencia p99 | <1ms |
| Cross-chain ops | 6/6 funcional |
| Pattern match (Jaccard) | 18-38% |
| model_scan speedup | **2,375×** (19s→8ms) |
| Wire savings | 10-59% (avg 29%) |

### Filesystem (13 tools) — vs Hermes built-in

| Tool | LUMEN | Hermes | Ratio |
|------|-------|--------|-------|
| search_files | 4.2ms | 43ms (grep) | **10.4×** |
| stream_read | 1.1ms | 29ms (head) | **26.8×** |
| read_files (bulk) | 3.2ms | 58ms (2 calls) | **18.1×** |
| search_filename | 2.1ms | 41ms (find+grep) | **19.8×** |
| **PROMEDIO** | **4.1ms** | **33ms** | **9×** |

### Cognitive Burst (200 ops mixtas)

| Operación | Resultado |
|-----------|-----------|
| Total time | 59ms |
| Avg latency | 0.29ms |
| Throughput | 3,407 calls/sec |
| Errors | 0 |

---

## 🔧 Herramientas Cross-Session — API Reference

### `agent_message`
Envía un mensaje a otra sesión de Hermes.

```json
{
  "to_session": "agent-b",
  "content": "Mensaje",
  "priority": "normal|high|urgent"
}
```

### `agent_inbox`
Lee mensajes recibidos.

```json
{
  "limit": 20,
  "unread_only": false
}
```

### `collision_check`
Detecta archivos modificados por múltiples sesiones en los últimos 5 minutos.

```json
{
  "window_seconds": 300
}
```

---

## 🧠 PDB — Process Database (La Memoria del Agente)

> **17 tools** · SQLite B-tree · Dual KV+SQL · Herencia MUMPS (1966)
> 15.5 μs GET · 30.8 μs SET · 81 MB de memoria persistente en este repo

### ¿Qué es?

Una base de datos jerárquica clave-valor con superpoderes de SQL. Sin esquemas, sin migraciones, sin DDL. El agente guarda datos como árboles:

```
^STATE("session:abc","chain:42","thought")     = "..."    ← cadenas de razonamiento
^STATE("global:objective:6")                     = {...}    ← agent loop objectives
^STATE("global:task:99")                         = {...}    ← tareas kanban
^CASITY("consent","device","AA:BB:CC:DD:EE:02") = true     ← escaneos WiFi
^SCRATCH("current_project")                      = "Casity" ← memoria efímera
```

Cada `^NS(sub1,sub2,...)=value` es un nodo en un B-tree. La primary key `(ns, subkey)` **es** el índice.

### ¿Por qué existe?

**1966 — MUMPS en el Massachusetts General Hospital.** Inventaron los "globals": árboles jerárquicos persistente sin esquemas. Con `SET`, `GET`, `ORDER` (next/prev hermano), `DATA` (¿existe? ¿tiene hijos?), `KILL` (borra subárbol). Las mismas 7 operaciones que tenemos hoy.

MUMPS se adelantó 30 años: jerárquico antes que MongoDB, atómico antes que Redis, sin esquemas antes que cualquier NoSQL. **Epic, el sistema de salud de EEUU, aún corre en MUMPS.** La VA, Kaiser, NHS — todos.

Pero MUMPS tenía sintaxis críptica, era propietario y no tenía SQL.

**2026 — PDB sobre SQLite.** Cogemos el modelo MUMPS y lo ejecutamos sobre SQLite. La tabla `_globals(ns, subkey, value)` es un B-tree puro. Las tools KV navegan el árbol (`$ORDER`, `$DATA`), el SQL lo consulta plano (`SELECT`, `GROUP BY`, `JOIN`). El LLM elige.

### Métricas en vivo

| Operación | Latencia | Throughput | 
|-----------|:--------:|:----------:|
| GET (exact key) | **15.5 μs** | 64,700/seg |
| SET (1 nivel) | **30.8 μs** | 32,500/seg |
| SET (3 niveles) | **56.2 μs** | 17,800/seg |
| $DATA (existe) | **33.9 μs** | 29,500/seg |
| $INCREMENT | **96.0 μs** | 10,400/seg |
| KILL (subárbol) | **26.7 μs** | 37,500/seg |
| $ORDER (next sibling) | **~5 μs** | ~200,000/seg |
| Batch (2,476 records) | **649 ms** | 3,817 rec/sec |
| FTS5 search | **~50 ms** | BM25 ranking |

Benchmark: 100K iteraciones, SQLite WAL, stdio JSON-RPC (SHM es 20× más lento para KV).

### Dual Interface

```python
# KV — navegación jerárquica (MUMPS-style)
pdb_order(ns="STATE", subs=["session:abc","chain"])   → next chain ID
pdb_data(ns="STATE", subs=["session:abc"])             → 10 (tiene hijos, sin valor)

# SQL — análisis plano
pdb_query("SELECT ns, COUNT(*) as n FROM _globals GROUP BY ns")
pdb_query("SELECT value FROM _globals WHERE value LIKE '%error%'")
```

### ¿Por qué no usar Redis / MongoDB / PostgreSQL?

| Sistema | Sin esquema | Jerárquico | ACID | SQL | Latencia GET |
|---------|:-----------:|:----------:|:----:|:---:|:-----------:|
| **PDB** | ✅ | ✅ | ✅ | ✅ | **15 μs** |
| Redis | ✅ | ❌ | ✅ | ❌ | ~50 μs |
| MongoDB | ✅ | ✅ | ❌ | ❌ | ~100 μs |
| PostgreSQL | ❌ | ❌ | ✅ | ✅ | ~100 μs |
| SQLite plano | ❌ | ❌ | ✅ | ✅ | ~10 μs |

PDB es el único que junta los cuatro: sin esquemas + jerárquico + ACID + SQL.

### En una línea

> *SQLite's B-tree es el mismo concepto que los globals de MUMPS — solo que 60 años más barato, más rápido, y con SQL.*

Ver también: [`implementations/mcp-servers/pdb/`](../implementations/mcp-servers/pdb/README.md) | [TOOLS_GUIDE → PDB section](../implementations/mcp-servers/TOOLS_GUIDE.md#pdb-database)

---

## 🏗️ Flujo de Trabajo Multi-Agente

```
┌──────────────────────────────────────────────────────────┐
│                 LUMEN Cognitive OS Dashboard              │
│  ┌─────────┐ ┌──────────┐ ┌───────────┐ ┌────────────┐ │
│  │  Wiki   │ │ 📬 Inbox │ │⚠️Collision│ │🧠 Patterns │ │
│  │  CRUD   │ │ agent→   │ │ auto-detect│ │ global     │ │
│  └─────────┘ └──────────┘ └───────────┘ └────────────┘ │
│                        │                                  │
│  ┌─────────────────────▼──────────────────────────────┐  │
│  │        Thinking Server (shared state in memory)     │  │
│  │  sessions │ model │ messages │ global_patterns     │  │
│  │  file_touches │ agent_messages │ call_timeline     │  │
│  └─────────────────────┬──────────────────────────────┘  │
│         │              │              │                    │
│    ┌────▼───┐    ┌─────▼────┐    ┌───▼─────┐           │
│    │ Agente │    │  Agente  │    │ Agente  │           │
│    │   A    │◄──►│    B     │◄──►│    N    │           │
│    └────────┘    └──────────┘    └─────────┘           │
└──────────────────────────────────────────────────────────┘
```

---

## 📈 Roadmap

| Fase | Estado | Features |
|------|--------|----------|
| **A — Wiki Mental** | ✅ | HTTP CRUD `/model`, `properties` en model_add, dashboard editor |
| **B — Cross-Session** | ✅ | `agent_message`, `agent_inbox`, `/collisions`, `/touch` |
| **C — Cognitive OS** | ✅ | `_global_patterns`, `collision_check`, `session_list` warnings, persistencia |
| **D — Auto-Negotiation** | 🔮 | Agentes negocian automáticamente al detectar colisiones |
| **E — Distributed** | 🔮 | Múltiples instancias de thinking server con sync |

---

## 📚 Referencias

- [Thinking Server README](../implementations/mcp-servers/thinking/README.md)
- [MCP Servers README](../implementations/mcp-servers/README.md)
- [TOOLS_GUIDE](../implementations/mcp-servers/TOOLS_GUIDE.md)
- [Benchmarks](../docs/benchmarks/internal/)
- [RFC LUMEN](../RFC_LUMEN.md)
- [Hermes Integration](../HERMES_INTEGRATION.md)
