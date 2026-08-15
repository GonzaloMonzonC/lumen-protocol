# ◆ SSOT — Fuente de Verdad Única (Arquitectura de Datos del Ecosistema)

> Decisión de Gonzalo (14-08-2026): *"no puede ser que Angie tenga su store y Zalo los suyos — somos un equipo"*.
> Este documento define **dónde vive cada dato** y las **convenciones del protocolo DDP-LUMEN**.
> Violar esto = crear una isla. Las islas están prohibidas.

---

## 1. Plano de datos (dónde vive cada cosa)

| Dato | Fuente canónica | Réplica / notas |
|---|---|---|
| **Tareas (kanban)** | `^KANBAN` — PDB local | Edge = réplica (sync diario). El kanban es UNO: tareas cognitivas + tareas PM de Angi (niche `pm-angi`) |
| **Decisiones** | `^DECISIONS` — PDB local | Angi registra aquí (no en su D1) |
| **Perfiles / relaciones / coaching / 360** | `^TEAM` — PDB local | Migración en curso (Fase 1 SSOT) |
| **Roadmaps / requirements / blockers** | `^PRODUCT` — PDB local | ✅ Fase 2 (15-08): Campo dual-write (`campo/src/product.ts`). D1 = espejo |
| **Agenda social (calendario)** | `^X_PUB(agenda,…)` — PDB local | ✅ Fase 3 (15-08): Angi dual-write (`angi/src/agenda.ts` → mirrorAgendaToXPub). D1 = espejo |
| **Contenido social (cola publicación)** | `^X_PUB` / `^X_STATE` — PDB local | ✅ Fase 2 (15-08): Gon dual-write. D1 = espejo |
| **Rutinas** | `^ROUTINE` — PDB local | Ya canónico |
| **Colaboración A2A** | `^COLAB` — PDB local | Ya canónico |
| **Sesiones de chat / eventos / caches** | D1 de cada worker | **Privado por agente** — efímero, NO se unifica |
| **KB (knowledge base)** | D1 de Zalo | La KB es de Zalo (única fuente) |

### Jerarquía
1. **PDB local** (M-Light sobre SQLite, casa, `vm-api.cadences.app`) = **canónico** para TODO dato compartido.
2. **Edge** (`pdb-edge` worker) = **réplica** para disponibilidad. Nunca fuente.
3. **D1 por worker** = solo privado/efímero.

### Sync edge↔local
- Cron diario 05:30 (`pdb-sync-diario`, wrapper **.py** — el resolver de bash del cron usa WSL en el host y está roto).
- Namespaces sincronizados: `KANBAN, COLAB, ROUTINE, DECISIONS, X_PUB, X_STATE` — **nunca** datos de sanidad (System/TRUST/HEALTH).
- Local gana; edge solo gap-fill o estrictamente más nuevo. Idempotente, checkpoint persistente.

### Escrituras de equipo
- Los workers escriben al PDB local vía `POST https://vm-api.cadences.app/ddp/push` (HMAC) — patrón probado con Zalo (lectura) y Angi (dual-write, Fase 1).
- **Regla dual-write**: D1 del worker = espejo/fallback durante transiciones; si el túnel falla, el worker sigue operando y el espejo se reconcilia después.

---

## 2. Protocolo DDP-LUMEN — convenciones del wire (aprendidas en producción, 14-08-2026)

1. **Push (`vm_api /ddp/push`)**: body `{ns, entries: [{subs: [string...], value}]}` — **subs en claro** (vm_api construye `SET ^NS("sub1","sub2")=value`). NO hex keys (ese es el formato del edge, no de vm_api).
2. **Read (`vm_api /ddp/raw`)**: soporta `ns`, `prefix` (coma-separado), `limit`, `offset`. **NO soporta `subs=`** — usar `prefix`. Devuelve meta/counter primero.
3. **Valores SIEMPRE JSON ASCII-safe** (`jsonEsc` → `\uXXXX`): el motor M-Light (Rust) **corrompe literales con unicode real** en M (`→` se guarda como mojibake cp1252 `â\x86\x92`). Con escapes `\u` round-trippea perfecto — y coincide con la convención del store (ensure_ascii).
4. **Fire-and-forget en Cloudflare Workers = cancelación**: los promises sueltos se matan al devolver la respuesta. Dual-writes SIEMPRE con `c.executionCtx.waitUntil(...)`.
5. **HMAC M2M**: `ts + raw_body + key` (POST) / `ts + path?query + key` (GET) — headers `X-DDP-Timestamp`, `X-DDP-HMAC`, clave compartida `DDP_HMAC_KEY`.
6. **⚠️ `tool_set` (pdb_tools local) espera valores RAW** — encoda él con `json.dumps(..., ensure_ascii=False)`; `tool_get` devuelve decodificado. Pasar valores pre-encodados = doble-encodado en el store (lecciones 15-08).
7. **⚠️ Bridge MCP de Hermes (Windows)**: los ARGS de tools con unicode llegan mojibakeados al worker (cp1252) — el path REST es limpio. Para contenido con acentos/unicode vía MCP, usar ASCII o ir por REST.
8. **Contadores atómicos**: `POST /ddp/allocate {ns, subs, step}` (vm_api) — lee+incrementa+devuelve en UN handler (servidor single-threaded = atómico entre clientes). El cliente canónico expone `kanbanAllocate()`; `pdbPushToKanban` lo usa — el id de tarea se asigna atómicamente (race del contador resuelto 15-08-2026: antes era GET /ddp/raw + POST /ddp/push = 2 round-trips con colisión posible).

### Dashboard unificado (Fase 3, 15-08-2026)
- **`GET /web/dashboard`** (vm_api, también por túnel `https://vm-api.cadences.app/web/dashboard`) — HTML con estado de los 9 workers, KANBAN meta, namespaces top y fuentes canónicas. Auto-refresh 60s.
- **`GET /api/status`** — JSON del mismo estado (para agents/cron). Workers: 200/404 = vivo (404 = sin handler raíz); 000 = caído.
- Nota: el meta de KANBAN se almacena como UN objeto JSON en `KANBAN(meta)` y **puede estar doble-encodado en reposo** (legacy) — parsear dos veces al leer raw.

### Cliente TS canónico (SSOT de código)
- **`implementations/typescript/src/ddp-client.ts`** = LA implementación TS del protocolo (hmacHex, pdbPush, pdbRead, jsonEsc, kanbanNextTaskId, helpers KANBAN).
- Los workers (Zalo, Angi, Lisa, Tom, Gon, Campo) **VENDEN este fichero** — `python implementations/typescript/sync_ddp_client.py --worker <w>` (o `--check` para detectar divergencias).
- **Nunca** implementar un cliente privado por worker.

---

## 3. KANBAN único — convenciones

- Las tasks viven en `^KANBAN(task, task_N, <campo>)` con campos: `title, status, priority, niche, owner, desc, src, src_id, created_at`.
- `status ∈ {backlog, in_progress, done}` · `priority ∈ {critical, high, medium, low}`.
- **Contador** `^KANBAN(counter, next_task)` = próximo id libre (inicializado a 764 el 14-08-2026). Todo agente que cree tasks lo lee/incrementa — evita colisiones de ids.
- **Meta** `^KANBAN(meta)` es un resumen DERIVADO: lo recomputa `reindex_kanban()` tras cada sync (nunca valores stale; tolerante a tasks sin status/priority).
- Los niches: `^KANBAN(niche, niche_N, name|desc|color)`. El niche `pm-angi` (91) agrupa las tareas de gestión de Angi.

---

## 4. Jerarquía MVM — Rust es el motor, Python es la capa

> Gonzalo: *"la buena es Rust"*. Veredicto del equipo (debate Smith `smith_3`, 15-08-2026): **la "MVM Python" no existe como intérprete** — es un bridge + tooling. La documentación debe dejar la jerarquía explícita para que nadie la confunda.

### Arquitectura de capas (Layered Architecture of Lumen-Protocol)

```text
┌──────────────────────────────────────────────────────────────┐
│  CAPA 4: APLICACIONES / AGENTES (Python — Business Logic)   │
│  MCP Servers, pdb-sync (orquestación), vm_api/poli_server   │
│  (Contienen lógica de flujo, pero NO ejecutan M).           │
├──────────────────────────────────────────────────────────────┤
│  CAPA 3: ACCESO / BINDINGS (Python — Thin Client)           │
│  lumen_mlight.py (ctypes FFI)                               │
│  [SOLO enlaza con la DLL Rust. No implementa nada.]         │
├──────────────────────────────────────────────────────────────┤
│  CAPA 2: LÓGICA DE NEGOCIO CORE (Rust — Exports)            │
│  MVM (intérprete, gas, ejecución de opcodes)                │
│  lumen-pdb (SQLite directo, persistencia)                   │
├──────────────────────────────────────────────────────────────┤
│  CAPA 1: RUNTIME / EMBEBIDO (Rust — Binary)                 │
│  lumen-m-light (motor ejecutable)                           │
└──────────────────────────────────────────────────────────────┘
```

### Reglas de documentación (para matar la confusión)
1. **El motor MVM canónico es Rust.** La capa Python es binding + orquestación. **No existe "MVM Python" como motor de producción** — prohibido ese término en docs/código; usar "Python Bindings for MVM Core" / "Orchestration Layer".
2. **✅ Invertido el default (15-08-2026)**: `pdb_tools.py` ahora usa **Rust por defecto** (`MLIGHT_ENGINE` default `"rust"`) tras verificar paridad de tests (fallos idénticos entre motores; Rust 6.4× más rápido: 12.7s vs 80.9s). El evaluador Python (`m_light.py`) queda como **fallback/legacy** con `MLIGHT_ENGINE=python`. `execute_sqlite(sqlite_path=...)` = modo directo Rust (camino canónico, vm_api). `MLIGHT_ENGINE_STRICT=1` = fallar si Rust no está disponible.
3. **Responsabilidades**: Rust = semántica de M, gas metering, persistencia SQLite, estado global · Python = I/O, HTTP, procesos, integración ML/LLM, sync, CLI.
4. **Contrato de dependencia**: `lumen_mlight.py` lleva el header "FFI wrapper — los bugs de lógica M se reportan al repo Rust".
5. **Versionado atado**: la versión del paquete Python referencia el hash del commit de la DLL Rust que envuelve (ej: `lumen_py-1.2.0 (binds lumen-mvm-core rev a4b9c)`).

### Qué aporta cada capa Python
| Componente | Rol | ¿Aporta? |
|---|---|---|
| `lumen_mlight.py` (ctypes FFI) | Driver de cliente (como psycopg2→PostgreSQL) | Sí — puerta de entrada al motor desde Python/LLMs |
| `pdb-sync` (DDP + sync) | Orquestador de datos edge↔local | Sí — transporte/reconciliación |
| `vm_api` / `poli_server` | Capa de APIs HTTP | Sí — expone el motor como servicio |
| MCP Servers | Capa de Agentes (LLMs consumen MCP) | Sí — **el oro**: sin esto los LLM no tocan el motor |
| Benches | Calidad/CI | Sí |

**Veredicto del equipo**: la capa Python **NO sobra** — aporta el ecosistema (adopción LLM, HTTP, sync). Rust gana en velocidad/seguridad; Python gana en velocidad de desarrollo y adopción. Lo que sobra es CUALQUIER intención de "MVM en Python".

---

## 5. Anti-islas — checklist de auditoría (Fase 3 SSOT)

- [ ] Cada tipo de dato del equipo tiene UNA fuente canónica en el PDB local.
- [ ] Los workers venden `ddp-client.ts` (no copias divergentes).
- [ ] Ningún worker guarda datos de equipo en su D1 (solo sesiones/eventos/caches).
- [ ] Ningún script usa `/ddp/raw` con `subs=` ni manda unicode real en pushes.
- [ ] El sync diario corre sin bash (wrapper .py) y es idempotente.
