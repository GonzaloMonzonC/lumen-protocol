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
| **Roadmaps / requirements / blockers** | `^PRODUCT` — PDB local | Migración en curso (Fase 2 SSOT, Campo) |
| **Contenido social (cola publicación)** | `^X_PUB` / `^X_STATE` — PDB local | Gon escribe aquí (drafts_cache D1 = solo cache) |
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

| Capa | Implementación | Rol |
|---|---|---|
| **Motor MVM (canónico)** | `implementations/rust/` — `lumen-m-light`, `lumen-mvm`, `lumen-pdb` | Intérprete M, gas, ejecución directa sobre SQLite. **La única MVM.** |
| **Bridge FFI** | `lumen_mlight.py` (ctypes → DLL Rust, `lm_execute_json`) | Python habla con el motor. Necesario, no es un motor. |
| **Tooling / servidores** | `pdb-sync/` (cliente DDP, motor de sync, vm_api), `poli_server.py`, MCP servers | Orquestación, HTTP, scripts. Nada de esto ejecuta M de forma canónica. |

**Qué aporta la capa Python**: sincronización edge↔local, HTTP APIs (vm-api/poli), tooling operativo, scripting rápido, MCP.
**Qué NO aporta**: ejecución de M. Cualquier intención de "MVM en Python" es un anti-patrón — el motor es Rust, punto.

---

## 5. Anti-islas — checklist de auditoría (Fase 3 SSOT)

- [ ] Cada tipo de dato del equipo tiene UNA fuente canónica en el PDB local.
- [ ] Los workers venden `ddp-client.ts` (no copias divergentes).
- [ ] Ningún worker guarda datos de equipo en su D1 (solo sesiones/eventos/caches).
- [ ] Ningún script usa `/ddp/raw` con `subs=` ni manda unicode real en pushes.
- [ ] El sync diario corre sin bash (wrapper .py) y es idempotente.
