# Arquitectura revisada — capas reales, política única, autoridad de escritura

**Fecha:** 2026-10-19 · **Estado:** diseño, sin código
**Origen:** corrección de Gonzalo + validación con Zalo y Smith (Poli)

---

## La corrección de Gonzalo (y por qué mi modelo anterior estaba mal)

> *"Lumen local PDB. Luego nodos LUMEN entre redes etc compartido según namespaces. Pero **Hermes no está ahí
> entre medio** — él está usando tools de LUMEN que tiran de esas herramientas LUMEN PDB. Luego el siguiente
> paso es unificarlo todo en un fondo cadences.app puro, de forma que podamos tener diferentes usuarios
> trabajando en una organización o varias, poniendo tareas en marcha y revisando toda la información generada
> en cada tarea. Volcar todo el contenido **si aceptas esta parte de diseño**."*

**Mi error:** modelé una federación de 3 niveles con Hermes como nodo intermediario. **Hermes no es un nodo de
datos: es un cliente de tools.** Y el volcado completo no es una decisión mía: **es del cliente.**

---

## Las cuatro capas reales

```
┌──────────────────────────────────────────────────────────────────┐
│ CAPA 4 · CADENCES.APP — backend de tools + actuación sobre nodos │
│   organizations · users · tasks · billing                        │
│   ★ PDP: authz, cuotas, auditoría (punto único de política)      │
└───────────────────────────┬──────────────────────────────────────┘
                            │  tools + token de decisión
┌───────────────────────────▼──────────────────────────────────────┐
│ CAPA 3 · HERMES — CLIENTE de tools, NO intermediario de datos    │
│   invoca tools LUMEN · no transporta contenido                   │
│   recibe intención + token firmado por el PDP                    │
└───────────────────────────┬──────────────────────────────────────┘
                            │  mcp:call / tools LUMEN
┌───────────────────────────▼──────────────────────────────────────┐
│ CAPA 2 · NODOS LUMEN — comparten por NAMESPACE                    │
│   ★ ACL por namespace + capacidad (macaroon con scope)           │
│   el nombre del namespace NO es la frontera                      │
└───────────────────────────┬──────────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────────┐
│ CAPA 1 · PDB LOCAL — autoridad de escritura de sus namespaces     │
│   export completo solo si el CLIENTE lo pide                     │
└──────────────────────────────────────────────────────────────────┘
```

---

## Los tres errores que Zalo cazó en este modelo

> *"**1. Tratas el namespace como frontera de seguridad.** Un namespace es lógico, no criptográfico: si un nodo
> comparte 2 namespaces, el receptor ya tiene todo lo que haya dentro. Necesitas ACL por namespace +
> capacidad/macaroon con scope, **no nombres**.*
>
> ***2. "Hermes no es intermediario" → te quedas sin punto de política.** Si cada tool habla directo con la PDB
> del nodo, la authz, cuotas y auditoría se duplican en cada tool, y el cliente se acopla a N versiones de nodo
> (N×M). **Hermes no debe ser cuello de botella de datos, pero sí punto único de autorización y
> contrato/versión.**
>
> ***3. El opt-in del volcado completo no te libera de nada.** Quien decide es el cliente, pero el tratamiento
> sigue siendo tuyo: DPA, cifrado por nodo y borrado verificable. Y te deja **dos semánticas** (index-only vs
> full-content) que la UI y las búsquedas deben distinguir… sin definir **quién tiene autoridad de escritura**
> sobre la tarea cuando org y nodo discrepan."*

**El punto 2 es el que cambia el diseño**: yo había quitado a Hermes del medio *como datos* (correcto) pero
también *como política* (incorrecto). **Datos y política son ejes distintos.**

---

## La arquitectura correcta (Smith, sobre las capas de Gonzalo)

> *1. **Capa 1**: PDB local por nodo = **autoridad de escritura de sus namespaces locales**; export completo
> solo si el cliente lo pide.
> 2. **Capa 2**: LUMEN expone **namespaces** (no nombres); **ACL se evalúa por namespace + rol**, nunca por
> nombre de recurso.
> 3. **Capa 3**: Hermes solo invoca tools LUMEN; **no transporta datos, solo intención + token de decisión**.
> 4. **Capa 4**: cadences.app = backend de tools + actuación sobre nodos; ahí vive el **PDP**
> (authz/cuotas/auditoría).
> 5. **Punto de política único**: toda tool→nodo pasa por PDP; sin token válido el nodo rechaza; auditoría se
> emite en el PDP, no en Hermes.
> 6. **Autoridad de escritura**: cada namespace declara **owner** (nodo u org). Owner=nodo → nodo gana, org
> solo lee/propone; owner=org → org escribe y el nodo aplica o rechaza por política local.
> 7. **Discrepancia org↔nodo**: se resuelve por **owner del namespace**, no por jerarquía; conflicto = write
> rechazado + evento de auditoría, **nunca merge silencioso**.
> 8. **Usuarios/orgs/tareas**: membership de org da roles sobre namespaces org-owned; **las tareas son objetos
> de cadences con ACL de namespace, no de nodo**.*"

**El concepto que resuelve todo es el #6: `owner` del namespace.** No una jerarquía, no un LWW, no un
"cadences manda". **Cada namespace declara quién manda en él.**

---

## Lo que hay hoy (medido)

| Pieza | Estado |
|---|---|
| PDB con namespaces | ✅ `_globals(ns, subkey, value)` — el `ns` es un string |
| **Owner de namespace** | ❌ **no existe** |
| **ACL por namespace** | ❌ **no existe** |
| **PDP / token de decisión** | ❌ **no existe** |
| Macaroons (capacidad con scope) | ✅ `macaroon.rs`, 16 funciones |
| `organizationId` en projects | ✅ `migrations/0010:125` |
| `permissions` (JSON, sin ACL) | ⚠️ existe, pero no normalizado |

Verificado ejecutando `PRAGMA table_info` sobre `~/pdb-data/lumen-pdb.db`: las tablas son `_globals`,
`_event_routes`, `_fts*`, `_vec_embeddings*`. **No hay tabla de namespaces, ni owner, ni ACL.**

---

## Lo que hay que construir, en orden

| # | pieza | capa | coste | por qué primero |
|---|---|---|---|---|
| **1** | **`owner` por namespace** en la PDB (`^NS_META(ns, "owner") = "node" \| "org:<id>"`) | 1 | **bajo** | sin esto no hay autoridad de escritura |
| **2** | **ACL por namespace + rol** (tabla ACL, no JSON) | 2 y 4 | medio | la frontera real |
| **3** | **PDP en cadences.app**: authz + cuotas + auditoría | 4 | medio | punto único de política |
| **4** | **Token de decisión** firmado (macaroon con scope `ns × rol × epoch`) | 3-4 | bajo (macaroon.rs ya existe) | Hermes pasa intención, no datos |
| **5** | **`org_nodes`** con `pubkey`, `epoch`, `revoked_at` | 4 | bajo | identidad + revocación |
| **6** | **Volcado full-content opcional** con DPA, cifrado por nodo, borrado verificable | 1→4 | **alto** | es del cliente, pero el tratamiento es tuyo |

**El 6 es el único caro**, y es precisamente el que Gonzalo quiere poder ofrecer. Los cinco primeros son
cimiento barato.

---

## Las dos semánticas que hay que distinguir en la UI

Zalo: *"te deja dos semánticas (index-only vs full-content) que la UI y las búsquedas deben distinguir."*

| Modo | Qué sube a cadences | Qué se puede hacer en la UI |
|---|---|---|
| **`index-only`** | metadatos + índice | buscar, ver que existe, **no ver contenido** |
| **`full-content`** (opt-in del cliente) | contenido completo | buscar, leer, revisar la tarea entera |

**La UI tiene que decir en cuál está cada tarea.** Si no, el usuario no sabe si lo que ve está completo o es
solo una referencia. Y la búsqueda devuelve resultados distintos en cada modo.

---

## La decisión que sigue abierta

**¿Quién es `owner` de `^KANBAN`?**

| Si owner = **nodo** | Si owner = **org** |
|---|---|
| El nodo manda; la org lee y propone | La org manda; el nodo aplica o rechaza |
| Kanban autónomo, offline pleno | Gobernanza central, multi-usuario |
| Dos usuarios no pueden editar la misma tarea | Los usuarios de la org trabajan juntos |

**Para lo que Gonzalo quiere al final** (usuarios en orgs poniendo tareas y **revisando la información de cada
tarea**) → **owner = org** en las tareas.

Pero los namespaces **de trabajo del nodo** (memoria, patrones, trazas) → **owner = nodo**.

**No es una decisión global: es por namespace.** Y ahí está la elegancia del modelo.

---

## Lo que no cambia

- **La infraestructura SaaS ya existe** (orgs, members, billing, api_keys, agents).
- **El nodo como miembro de primera clase** sigue siendo el concepto.
- **Hermes no es nodo de datos** — Gonzalo tiene razón y Zalo lo confirma: solo intención + token.
- **Macaroons ya están** en el repo: la capa de capacidad no hay que inventarla.
