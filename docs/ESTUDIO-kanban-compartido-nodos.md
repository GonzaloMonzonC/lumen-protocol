# Estudio — Kanban compartido entre nodos LUMEN y Hermes (punto único de verdad)

**Fecha:** 2026-10-19 · **Estado:** estudio previo, sin código
**Idea de Gonzalo:** *"conectar sesiones LUMEN con el kanban/tareas/proyectos de cadences.app para que hubiera
un punto final compartido entre nodos LUMEN y nodos Hermes vía MCP"*

---

## El hallazgo que ordena el problema: **ya hay TRES kanbans**

Antes de diseñar nada, el inventario real:

| # | Kanban | Dónde vive | Quién lo escribe | Filas hoy |
|---|---|---|---|---|
| **A** | **PDB `^KANBAN`** | `~/pdb-data/lumen-pdb.db` (SQLite local) | MCP thinking (`task_*`), Poli, agentes M | **4.330** |
| **B** | **`tasks` (D1 ProjectOS)** | Cloudflare D1 `projectos-db` | cadences.app (UI), API | ? (producción) |
| **C** | **`synapse_tasks` (D1)** | mismo D1, `0097_synapse_studio.sql` | Synapse Studio | ? |

**Y no se hablan entre sí.** El de Hermes/Poli es A; el de la web es B. Son **dos verdades distintas del mismo
concepto**, cada una con su esquema.

### Por qué esto importa más que el transporte

La pregunta natural sería *"¿cómo conecto A con B por MCP?"*. Pero el problema real es anterior:

> **`^KANBAN` y `tasks` no comparten ni identificadores ni semántica de estado.**

| | `^KANBAN` (PDB) | `tasks` (D1) |
|---|---|---|
| ID | `task_257` (secuencial, regenerable) | `id TEXT PRIMARY KEY` (uuid) |
| Estado | columnas kanban: `backlog/in progress/review/done` | `pending/in_progress/completed/cancelled/blocked` |
| Proyecto | `niche_id` (14 nichos, algunos "Test") | `projectId` + `customerId` |
| Prioridad | `critical/high/medium/low` | `0/1/2/3` numérico |
| Jerarquía | plana + nichos | tareas + sub-tareas (`checklist` JSON) |

**Mapear esto a posteriori es imposible sin pérdida.** Si se sincronizan sin un identificador común, cada
sync crea duplicados — y ya hemos visto lo que pasa con eso (`task_230` infló el kanban de 709 a 232 por
escrituras fallidas).

---

## Las tres arquitecturas posibles

### Opción A — Hub-and-spoke: **cadences.app como verdad única** (recomendada)

```
   Hermes (PC)  ──┐
   Hermes (Asus)──┤
   Poli          ─┼── MCP ──►  cadences.app /api/kanban  ──►  D1 (verdad única)
   Zalo          ─┤                    │
   Agentes M     ─┘                    └──►  UI web
```

**Cómo:** un **servidor MCP** (`lumen-kanban-mcp`) que expone las operaciones del kanban y habla con la API de
cadences.app. Todos los nodos usan *ese* MCP. La PDB local deja de tener `^KANBAN` propio: pasa a ser **caché
de lectura** o desaparece.

| ✅ A favor | ❌ En contra |
|---|---|
| **Un solo punto de verdad** — es literalmente lo que pides | Requiere red; offline no funciona |
| La UI web es un cliente más, no un caso especial | Latencia (~100-300 ms por op) |
| Sin conflictos: D1 serializa | Hay que migrar los 4.330 registros de `^KANBAN` |
| Los agentes M lo usan por `mcp:call` (ya existe) | cadences.app pasa a ser dependencia crítica |

### Opción B — PDB como verdad única, la web como cliente

```
   cadences.app UI ──► pdb-edge ──► D1 edge ──► DDP ──► PDB local
   Hermes/Poli ──────► PDB local (directo, 0,14 ms)
```

**Cómo:** ya existe DDP (`^COLAB`, pdb-edge). El kanban vive en PDB y la web lee vía edge.

| ✅ A favor | ❌ En contra |
|---|---|
| Los agentes leen a **0,14 ms** (local) | La web depende de que un nodo esté online |
| Funciona offline en el nodo | DDP es unidireccional en la práctica (`^COLAB` lo dice) |
| Coherente con "PDB first" | Conflictos si dos nodos editan sin conexión |

### Opción C — Federación con LWW y IDs canónicos

```
   Hermes PC ──┐
               ├── cada nodo su PDB ── DDP bidireccional ── merge LWW
   Hermes Asus─┘
```

**Cómo:** cada nodo mantiene su kanban; DDP sincroniza con *last-write-wins* y un ID global (`uuid` + `node_id`).

| ✅ A favor | ❌ En contra |
|---|---|
| Robusto sin red; escala a N nodos | **El más caro** y el más difícil de depurar |
| No hay punto único de fallo | LWW pierde ediciones concurrentes silenciosamente |
| | Ya está el bug DDP de "pierde datos en silencio" (`task_221`) |

---

## Recomendación: **A, pero por fases**

### Fase 0 — El identificador común (sin esto, nada funciona)

**Añadir `uid` (UUID v4) a `^KANBAN` y a `tasks`.** Un `uid` no cambia con el sync, no se regenera y no depende
del nodo.

```python
# en la creación, ambos lados
task["uid"] = str(uuid.uuid4())   # inmutable, viaja en el sync
task["id"]  = "task_257"          # local, no viaja
```

Emparejamiento: `^UID_MAP(uid) -> {node, local_id}`. Es la pieza que evita los duplicados.

**Coste:** bajo. **Sin esto, A, B y C fallan todas.**

### Fase 1 — MCP de kanban (el conector que pides)

Un servidor MCP nuevo, `lumen-kanban`, con las **7 tools de `task_*`** que ya existen, pero **respaldado por
cadences.app**:

| Tool | Implementación |
|---|---|
| `task_list` | `GET /api/kanban/tasks` |
| `task_create` | `POST /api/kanban/tasks` (con `uid`) |
| `task_move` | `PATCH /api/kanban/tasks/:uid` (cambio de columna) |
| `task_search` | `GET /api/kanban/tasks?q=` |
| `task_delete` | `DELETE /api/kanban/tasks/:uid` |
| `task_link` / `task_link_url` | igual, por `uid` |

**Y aquí está la conexión con lo que ya hicimos:** la MVM ya tiene `mcp:call` y `^TOOLS` acepta
`kind = "mcp:server/tool"`. **Un agente M podría usar el kanban compartido sin escribir una línea de Rust.**
Solo registraría `^SYS("MCP","kanban",url,"http")` y pondría las entradas en `^TOOLS`.

### Fase 2 — Migración de los 4.330 registros

Con `uid` asignado, volcar `^KANBAN` → D1. **Una vez**, con dry-run y verificación de conteo.

### Fase 3 — La PDB local como caché

`^KANBAN` deja de ser la verdad. Se llena desde la API (con TTL corto) para lecturas rápidas. Si el nodo está
offline: **lee la caché, no escribe** (modo degradado explícito, no silencioso).

---

## Lo que hay que decidir antes de empezar

| Decisión | Opciones | Mi recomendación |
|---|---|---|
| **¿Dónde está la verdad?** | A (cadences.app) / B (PDB) / C (federado) | **A** — es lo que pediste y evita conflictos |
| **¿Migrar los 4.330 registros?** | Volcado único con `uid` | **Sí, Fase 2** |
| **¿Los 14 nichos → qué?** | `projectId` en D1 | Necesita mapeo; **9 nichos son "Test"** que conviene borrar antes |
| **¿Offline?** | Caché solo-lectura / sin soporte | **Caché solo-lectura** (degradación explícita) |
| **¿Autenticación?** | API key + HMAC (como el resto) | **HMAC** (`X-DDP-HMAC`), ya probado |

---

## Riesgos

| Riesgo | Mitigación |
|---|---|
| **Migrar 4.330 filas con duplicados** | Fase 0 (`uid`) **antes** de cualquier volcado; dry-run y verificación de conteo |
| **Latencia en cada op** (~100-300 ms) | Caché local de lectura; escrituras asíncronas en el agente |
| **cadences.app cae → agentes sin kanban** | Caché solo-lectura; degradación explícita |
| **Dos escrituras simultáneas del mismo `uid`** | D1 serializa; con `uid` es un `PATCH`, no un insert |
| **Se pierde el trabajo local offline** | Modo solo-lectura: **no se escribe**, se avisa |

---

## Lo que NO propongo

- **No** federar (C) ahora: el bug de DDP que pierde datos (`task_221`) sigue abierto. Sincronizar dos kanban
  sobre un transporte que pierde datos en silencio es garantizar corrupción.
- **No** sincronizar `^KANBAN` ↔ `tasks` directamente: sin `uid` común, es una fábrica de duplicados.
- **No** empezar por el MCP: sin `uid` y sin decidir la verdad, el MCP solo hace más rápido lo incorrecto.

---

## Primer paso concreto (y barato)

**Fase 0: añadir `uid` a `^KANBAN`.** Es un paso, no toca la web, no toca el transporte y **desbloquea las tres
arquitecturas**. Se puede hacer hoy y verificar con un test de idempotencia.

Todo lo demás depende de eso.
