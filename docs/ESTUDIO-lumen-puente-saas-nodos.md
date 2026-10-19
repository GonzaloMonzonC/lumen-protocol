# Estudio — LUMEN como puente entre SaaS organizacional y nodos autónomos

> ⚠️ **REVISADO 2026-10-19 tras validación con Zalo y Poli.** Este estudio tiene un error de fondo que
> invalida su primera versión: **"subir solo el índice" NO preserva la soberanía** (el índice es contenido y,
> sin aislamiento por `org_id`, filtra entre organizaciones). Y el orden de pasos estaba invertido: el
> aislamiento va ANTES de `org_nodes`. Ver `VALIDACION-puente-saas-nodos.md` para las correcciones y el orden
> correcto. Lo que sigue siendo válido: la infraestructura SaaS ya existe y el concepto de "nodo como miembro".

**Fecha:** 2026-10-19 · **Estado:** estudio, sin código
**Origen:** idea de Gonzalo — *"comercializar LUMEN como un puente entre organización SaaS y nodos autónomos,
donde los agentes pivoten sobre cadences.app o sus subredes pero con respaldo a cadences"*

**Corrección de rumbo:** este estudio mira **cadences.app (ProjectOS), NO Synapse Studio**. El estudio anterior
(`ESTUDIO-kanban-compartido-nodos.md`) se quedó corto: trataba el kanban como el problema, cuando el kanban es
solo **una tabla** dentro de algo mucho más grande.

---

## El hallazgo: **la infraestructura multi-tenant ya existe**

He auditado `ProjectOS` (123 endpoints, ~150 migraciones). Lo que ya está construido:

| Pieza | Tabla / endpoint | Estado |
|---|---|---|
| **Organizaciones** | `organizations` — billing, plan, límites, trial | ✅ construido |
| **Miembros y roles** | `organization_members` — `owner/admin/member/readonly` | ✅ construido |
| **Proyectos por org** | `projects.organizationId` + `scope` + `isOrgShared` | ✅ construido |
| **API keys por org** | `organization_api_keys` — clave por proveedor, con `api_key_mode` | ✅ construido |
| **Planes y billing** | `billing_plans` (0025), `tier_assignments`, Stripe | ✅ construido |
| **Agentes** | `ai_agents`, `project_agents`, `agents/[[path]]` | ✅ construido |
| **Workflows** | `workflows` + `executions` + `nodeSchemas` | ✅ construido |
| **Dispositivos** | `devices` (IoT/edge) | ✅ construido |

> **No hay que inventar el modelo de negocio: hay que conectar LUMEN a él.**

Esto cambia el estudio por completo. La pregunta ya no es *"¿cómo compartimos un kanban?"* sino
**"¿cómo se presenta un nodo LUMEN como un miembro más de la organización?"**

---

## La arquitectura que tu idea habilita

```
┌─────────────────────────────────────────────────────────────────┐
│  CADENCES.APP  (SaaS · D1 · la verdad organizacional)           │
│                                                                 │
│   organizations ── members ── projects ── tasks ── workflows    │
│        │                                                        │
│        └── organization_api_keys  (OpenAI, ElevenLabs, …)       │
│        └── billing_plans / tier_assignments  (Stripe)           │
└────────────────────────┬────────────────────────────────────────┘
                         │  MCP (LUMEN)  ·  HMAC  ·  por organización
        ┌────────────────┼────────────────┐
        │                │                │
   ┌────▼────┐     ┌─────▼─────┐    ┌─────▼─────┐
   │ Nodo    │     │ Nodo      │    │ Nodo      │
   │ Hermes  │     │ Hermes    │    │ MVM       │
   │ (PC)    │     │ (Asus)    │    │ (LUMEN OS)│
   │  PDB    │     │  PDB      │    │  PDB      │
   └─────────┘     └───────────┘    └───────────┘
        Autónomos: siguen trabajando offline
        Subordinados: lo que importa sube a cadences
```

### Los tres conceptos que hay que definir (y no existen)

| # | Concepto | Qué resuelve | Dónde encaja |
|---|---|---|---|
| **1** | **Nodo como miembro** | Un nodo LUMEN es un `organization_member` con `role = 'node'` | `organization_members` (+ campo `kind`) |
| **2** | **Identidad de nodo** | Qué nodo es, en qué organización, con qué clave | nueva tabla `org_nodes` |
| **3** | **Respaldo jerárquico** | El nodo es dueño de sus datos; la org tiene el índice | `scope` + `isOrgShared` ya existen |

---

## El modelo propuesto: **soberanía local, respaldo organizacional**

Esto es lo que hace comercializable la idea, y es distinto de "SaaS con clientes":

| | SaaS clásico | **LUMEN + cadences** |
|---|---|---|
| Datos | en el servidor del proveedor | **en el nodo del cliente** |
| IA | la que el proveedor paga | **la del nodo** (o `organization_api_keys` si el cliente no tiene) |
| Offline | no funciona | **sigue trabajando** |
| Respaldo | backup del proveedor | **sincronización hacia cadences** (index + auditoría) |
| Coste marginal por cliente | alto | **~0** (el cómputo es del cliente) |

**La propuesta de valor:** *"tu organización en la nube, tu inteligencia en tu nodo"*. La org obtiene
gobernanza, auditoría y respaldo; el cliente mantiene soberanía y coste.

Y **esto enlaza con lo que ya tenemos**: `organization_api_keys` significa que **un nodo puede usar la clave
del cliente o la de la org**, y `api_key_mode` (`inherit | organization | member`) **ya resuelve ese problema**.
No hay que diseñarlo: está en `migrations/0045`.

---

## Qué se expone por MCP (el conector)

Un servidor MCP, `lumen-org`, con un catálogo pequeño — coherencia con P0-1:

| Tool | Qué hace | Tabla |
|---|---|---|
| `org_info` | qué organización, qué plan, qué límites | `organizations` |
| `org_projects` | proyectos de la org visibles al nodo | `projects` (`organizationId`) |
| `org_tasks` | tareas de esos proyectos | `tasks` |
| `org_task_create` / `org_task_update` | escribir tareas | `tasks` |
| `org_agents` | agentes registrados | `ai_agents`, `project_agents` |
| `org_backup_push` | subir el índice del nodo | nueva `org_nodes` |
| `org_backup_pull` | recuperar estado en un nodo nuevo | nueva `org_nodes` |

**Siete tools.** Y todas se pueden llamar desde la MVM con `mcp:call` — **sin escribir Rust**.

---

## Por qué esto sí es comercializable

| Lo que el cliente quiere | Lo que cadences da | Lo que LUMEN añade |
|---|---|---|
| "No quiero mis datos en tu nube" | — | **datos en el nodo** |
| "Quiero que funcione sin internet" | — | **offline real** |
| "Quiero auditoría de lo que decide la IA" | — | **digest + replay** (estudio del juego) |
| "No quiero pagar por token" | — | **cómputo propio** |
| "Quiero gobernar a mis empleados/agentes" | ✅ org + roles | — |
| "Quiero facturar por uso" | ✅ billing + planes | — |

**Cadences aporta el SaaS. LUMEN aporta la soberanía.** Ninguno de los dos lo tiene solo.

---

## Lo que falta construir (y es poco)

| # | Pieza | Coste | Bloqueante |
|---|---|---|---|
| **1** | `org_nodes`: tabla + endpoint + MCP | **bajo** | — |
| **2** | `uid` en `tasks` y `^KANBAN` (del estudio anterior) | **bajo** | sí, para sync |
| **3** | MCP `lumen-org` (7 tools) | **medio** | 1, 2 |
| **4** | `org_backup_push/pull` — índice del nodo a D1 | **medio** | 1 |
| **5** | Degradación offline explícita (lee caché, no escribe) | **medio** | 4 |
| **6** | UI: el nodo como miembro en el panel de la org | **medio** | 1 |

**Nada de esto requiere tocar lo que ya funciona.** Es añadir una tabla y un MCP.

---

## Riesgos

| Riesgo | Por qué importa | Mitigación |
|---|---|---|
| **Confundir "respaldo" con "sincronización"** | Sync bidireccional = conflictos; respaldo = un sentido | **`push` es unidireccional a D1**; el nodo manda |
| **El nodo escribe en `tasks` y la UI también** | Dos editores | `uid` + `version` (ya existe en `0064_add_versioning.sql`) |
| **Datos sensibles del cliente en D1** | Soberanía se pierde | Solo sube **índice + metadatos**, nunca el contenido completo |
| **Depender de cadences para arrancar** | Si cae, el nodo no opera | Nodo arranca con su PDB; cadences es opcional |
| **Multi-tenant mal aislado** | Fuga entre orgs | `organizationId` en TODA query (ya es el patrón) |

---

## Lo que NO propongo

- **No** meter el contenido del nodo en D1. Sube **el índice** (qué hay), no **el qué**.
- **No** sync bidireccional. `push` del nodo a la org; `pull` solo para recuperación.
- **No** tocar `synapse_*` (Synapse Studio). Es otro producto.
- **No** federar nodos entre sí (bug DDP `task_221` sigue abierto).

---

## Primer paso: `org_nodes`
```sql
CREATE TABLE IF NOT EXISTS org_nodes (
  id            TEXT PRIMARY KEY,        -- node_<uuid>
  organizationId TEXT NOT NULL,          -- FK organizations
  name          TEXT NOT NULL,           -- "PC-desarrollo", "Asus", "neferu"
  kind          TEXT NOT NULL,           -- hermes | mvm | poli
  publicKey     TEXT,                    -- identidad (macaroon / Ed25519)
  lastSeenAt    TEXT,
  status        TEXT DEFAULT 'active',   -- active | offline | revoked
  meta          TEXT,                    -- JSON: versión, capacidad, ubicación
  createdAt     TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (organizationId) REFERENCES organizations(id) ON DELETE CASCADE
);
```

**Es una tabla y un endpoint.** Con eso, un nodo LUMEN "existe" para la organización — que es el requisito
para todo lo demás y para poder venderlo.

---

## Conclusión

**Tu intuición es correcta y el momento es bueno:** la parte SaaS (orgs, roles, billing, API keys, agentes,
workflows) **ya está construida**. Lo que falta es la pieza LUMEN: **el nodo como miembro de primera clase**,
con soberanía local y respaldo organizacional.

Eso no es "un kanban compartido". Es un **modelo de producto**:
> **SaaS para gobernar, nodo para poseer.**

Y el primer paso es una tabla: `org_nodes`.
