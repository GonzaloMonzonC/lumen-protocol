# Validación con Zalo y Poli — LUMEN como puente SaaS ↔ nodos

**Fecha:** 2026-10-19 · **Consultados:** Zalo (KB del ecosistema), Poli en modo Astrid y Smith
**Veredicto:** **la idea se sostiene, pero tal como estaba planteada tenía un fallo que la mata.**
Los tres consultados coinciden en cuál y en cómo arreglarlo.

---

## Lo que Zalo encontró: **8 agujeros**, no opiniones

> *"1. **Identidad**: un nodo no es un usuario. Necesitas claves de nodo + macaroons delegados con
> revocación; si no, es una api-key glorificada sin dueño.
> 2. **Solo-índice no es privacidad**: el índice filtra contenido (términos, cardinalidades, embeddings →
> inversión semántica).
> 3. **Push unidireccional sin ack ni revocación**: nodo dado de baja sigue con copia del índice. Falta
> epoch + CRL + tombstones.
> 4. **Sin retorno no hay prueba de vida ni de cómputo**: billing por nodo es inauditable; **sybil trivial**
> (10 nodos falsos = 10 asientos).
> 5. **Offline = deriva**: sin snapshots firmados y resync por merkle, el índice diverge en dos semanas.
> 6. **Permisos**: el índice no es row-level; un nodo con 3 roles sube un índice con visibilidades mezcladas.
> 7. **GDPR**: índice en endpoint del cliente = tratamiento fuera de frontera.
> 8. **Monetización**: si el nodo no devuelve contenido, **cobras presencia, no uso**. El valor está en la
> org, el coste en el nodo."*

Los ocho son reales. **Cuatro de ellos (2, 4, 6, 8) invalidaban la propuesta de valor que escribí.**

---

## El fallo mortal (consenso de las tres fuentes)

**Astrid** (con los datos verificados):
> *"El más grave para comercializar es el **aislamiento/fuga de contenido multi-tenant vía índice de nodo**,
> no el billing sybil. Con `permissions` en JSON sin RLS por proyecto, `projects` sin `visibility` por fila y
> sin `org_nodes`, **no hay frontera técnica verificable**. Eso rompe confianza enterprise, bloquea contratos
> y crea responsabilidad legal."*

**Verificado en código** (`ProjectOS`):

| Afirmación | Verificado |
|---|---|
| `permissions` es JSON suelto, sin ACL normalizada | ✅ `migrations/0010:60` — `permissions TEXT -- JSON` |
| `projects` no tiene visibilidad por fila | ✅ solo `organizationId`, `scope`, `isOrgShared` |
| No existe `org_nodes` | ✅ no hay tabla con ese nombre |

**Consecuencia:** mi afirmación *"sube solo el índice, no el contenido → soberanía preservada"* **es falsa**.
El índice **es** contenido: revela términos, cardinalidades y estructura. Un índice sin aislamiento por fila
**filtra entre organizaciones**.

---

## Los 3 cambios que la hacen vendible (sin rediseñar)

**Smith:**
> *"Son cimientos, no features:*
> *1. **Aislamiento real por tenant en `projects` + índice.** `org_id NOT NULL`, RLS forzado con política por
> `current_setting('app.org_id')`, rol de app sin bypass. El índice particionado/namespaced por `org_id` y
> consultado con `org_id` obligatorio: **que sea incapaz de devolver contenido de otra org**, no un filtro
> posterior.*
> *2. **`org_nodes` como contrato de identidad y revocación.** `org_id`, `node_id`, `pubkey`, `status`,
> `revoked_at`, `epoch`, `region/retention`. Tokens de push cortos, firmados y atados a
> `org_node_id + epoch`; el gateway comprueba revocación. Cierra push sin revocación, deriva offline y parte
> de GDPR.*
> *3. **Normalizar permisos y billing por org.** Sacar `permissions` JSON a tabla ACL (`org_id`, `node_id`,
> `subject`, `role`) con RLS; el JSON queda como caché. **Billing y cuotas ligados a `org_id` con aprobación
> de nodo**, no a identidad de nodo: mata sybil billing y hace monetizable el puente."*

---

## Correcciones al estudio `ESTUDIO-lumen-puente-saas-nodos.md`

| Lo que escribí | Corrección |
|---|---|
| "Sube solo el índice, no el contenido → soberanía preservada" | **Falso.** El índice es contenido. Sin aislamiento por `org_id`, filtra entre organizaciones |
| "Primer paso: `org_nodes`" | **Correcto**, pero **no es el primero**: antes hay que **normalizar el aislamiento** (RLS en `projects`) y **sacar `permissions` del JSON** |
| "Push unidireccional" | **Incompleto.** Necesita `epoch` + revocación + tombstones, o un nodo dado de baja sigue con copia |
| "Cobrar por presencia" | Tal como estaba, **sí**: si el nodo no devuelve contenido, se cobra asiento, no uso. Hay que decidir cuál de los dos es el modelo |
| "Offline real" | **Riesgo de deriva.** Sin snapshots firmados y resync por merkle, diverge en dos semanas |

---

## El orden correcto, revisado

| # | paso | por qué este orden |
|---|---|---|
| **0** | **RLS en `projects` + ACL normalizada** (sacar `permissions` del JSON) | sin esto, el índice filtra entre orgs. **Es el fallo mortal** |
| **1** | `org_nodes` con `pubkey`, `epoch`, `revoked_at` | identidad + revocación + base de GDPR |
| **2** | `uid` en `tasks` y `^KANBAN` | el sync sin identificador común duplica |
| **3** | MCP `lumen-org` (7 tools) | ya con frontera verificable |
| **4** | Índice namespaced por `org_id` + resync por merkle | evita deriva offline |
| **5** | Decidir modelo de cobro: **presencia o uso** | determina qué se mide |

**Mi propuesta anterior ponía el paso 0 como último.** Es el primero.

---

## Lo que sigue en pie de la idea

- **La parte SaaS ya existe** (`organizations`, `organization_members`, `organization_api_keys` con
  `api_key_mode`, `billing_plans`, `ai_agents`, `workflows`). Eso no lo discute ninguna de las tres fuentes.
- **El nodo como miembro de primera clase** es el concepto correcto.
- **Cadences aporta gobernanza; LUMEN aporta soberanía** — sigue siendo la propuesta de valor, **pero solo si
  el aislamiento es verificable**.

---

## Lo que hay que decidir antes de escribir código

1. **¿Presencia o uso?** Si el nodo no devuelve contenido, se cobra asiento (sybil-trivial). Si devuelve
   contenido, se pierde la soberanía. **Hay que elegir y no se puede tener las dos.**
2. **¿GDPR: dónde vive el índice?** Si el índice está en el nodo, la org no puede buscar sin consultarlo.
   Si está en D1, no es soberanía. Tercera vía: índice cifrado con clave del cliente.
3. **¿`org_id` obligatorio en todas las queries** o RLS de base de datos? Smith propone RLS; es más caro pero
   es la única frontera *verificable*.

---

## Conclusión

> **La idea es buena y comercializable, pero mi primera versión vendía soberanía sin tener el aislamiento que
> la hace real.** Zalo encontró 8 agujeros; Astrid identificó el mortal; Smith dio los tres cimientos.

**No hay que rediseñar el producto: hay que poner los cimientos antes que las paredes.** Y el primer cimiento
es RLS por organización, no `org_nodes`.

**Ninguno de los tres dijo que la idea fuera mala.** Los tres dijeron, con distintas palabras, lo mismo:
*"el modelo está bien, pero sin frontera verificable no se puede vender a una empresa".*
