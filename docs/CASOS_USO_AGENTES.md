# Casos de uso A2A: agentes que comparten Namespaces entre nodos

> Estado: guía de arquitectura, 2026-07-15. Complementa la spec M-Agent v0.3.
> Los actores de este documento son agentes, Jobs MVM y nodos. Una persona no
> forma parte del flujo de ejecución.

## 1. Qué problema resuelve

LUMEN no debe modelar estos casos como una aplicación que presenta datos a una
persona. El producto es una red de agentes que:

- comparte hechos y trabajo mediante Namespaces PDB replicados por DDP;
- se notifica mediante mailboxes, enviando referencias en vez de duplicar datos;
- persiste su ejecución en la MVM;
- puede quedar en `WAITING` o `HIBERNATE` sin consumir CPU;
- puede trasladar su estado a otro nodo y continuar desde la misma instrucción;
- delega acceso con macaroons limitados por Namespace y operación.

Hay tres planos distintos:

| Plano | Primitiva | Qué transporta |
|-------|-----------|-----------------|
| Datos | PDB + DDP | Hechos, tareas, resultados, artefactos y eventos compartidos |
| Control | Mailbox MVM | Avisos pequeños que apuntan a un dato del Namespace |
| Ejecución | `^STATE`, `^PROCESSES`, `^SCHEDULE` | Estado durable, gas, mailbox y próximo despertar del Job |

El Namespace es la fuente de verdad. El mailbox solo acelera la reacción. Si un
aviso se pierde o llega duplicado, el agente reconstruye el estado leyendo el
Namespace y el journal DDP.

## 2. Contrato A2A común

### 2.1 Identidades

- `agent_id`: identidad lógica estable, por ejemplo `planner-7`.
- `node_id`: máquina que ejecuta el agente, por ejemplo `edge-bcn-02`.
- `pid`: instancia local de un Job MVM. Puede cambiar al importar el estado en
  otro nodo, por lo que nunca se usa como identidad global del agente.
- `run_id`: ejecución lógica que sobrevive a reintentos y migraciones.

El router resuelve `agent_id → node_id → pid` consultando `^PRESENCE`. El emisor
nunca persiste el PID remoto como dirección durable: tras una migración vuelve a
resolver la identidad lógica antes de entregar el mensaje.

### 2.2 Sobre de mensaje

Un mensaje A2A lleva control, no el resultado completo:

```json
{
  "v": 1,
  "id": "msg-01JZ...",
  "type": "task.ready",
  "from": "planner-7",
  "to": "capability:research",
  "namespace": "KANBAN",
  "ref": ["campaign-42", "task", "T-18"],
  "correlation_id": "campaign-42",
  "causation_id": "evt-1042",
  "idempotency_key": "campaign-42:T-18:ready:3",
  "created_at": "2026-07-15T12:00:00Z",
  "ttl_seconds": 300
}
```

El receptor deduplica por `idempotency_key` y después lee el valor vigente de
`^KANBAN("campaign-42","task","T-18")`. No ejecuta ciegamente el contenido
del mensaje.

### 2.3 Propiedad y exclusión entre nodos

Cada unidad ejecutable mantiene un lease:

```text
^KANBAN(space,"task",task,"lease") = {
  owner_agent, owner_node, epoch, acquired_at, expires_at
}
```

`epoch` es un fencing token monótono. Un agente solo publica efectos si el
`epoch` de su lease sigue siendo el vigente. Renovar un lease vencido incrementa
el token; cualquier resultado de un propietario anterior queda obsoleto.

`$LOCK` protege concurrencia sobre la PDB compartida por un proceso o por un
nodo, pero no es por sí solo un lock distribuido entre réplicas DDP. Los casos
multi-nodo DEBEN usar una de estas políticas:

1. un nodo autoritativo concede leases y fencing tokens; o
2. un coordinador con compare-and-set linealizable concede la propiedad.

La resolución por timestamp de DDP sirve para replicar datos, no para elegir de
forma segura dos propietarios concurrentes.

### 2.4 Entrega, orden e idempotencia

- DDP reintenta cambios no confirmados: la aplicación asume entrega
  **at-least-once**.
- `^CHANGES("journal",seq)` ordena cambios dentro del journal de un nodo; no es
  un reloj global entre nodos.
- Todo efecto externo incluye `run_id`, `idempotency_key` y `lease.epoch`.
- Un consumidor avanza su cursor solo después de persistir el efecto o su ack.
- Un `KILL` replicado se trata como una operación idempotente.

### 2.5 Autorización

Cada agente recibe la capacidad mínima necesaria:

| Rol de agente | Lectura | Escritura |
|---------------|---------|-----------|
| Planner | campaña completa | plan, dependencias y tareas nuevas |
| Worker | tarea asignada + dependencias | lease, progreso y resultado propio |
| Reviewer | especificación + resultado | veredicto y evidencias de revisión |
| Migrator | snapshot de un `run_id` | protocolo de migración y ack |
| Observer | eventos y métricas | ninguna |

Los macaroons deben incluir `ns_prefix`, `op` y `expiry`. Un agente puede
atenuar una capacidad al delegarla, pero nunca ampliarla.

## 3. Resumen de casos

| ID | Caso | Namespaces principales | Estado MVM |
|----|------|------------------------|------------|
| A2A-01 | Kanban/campaña compartida | `^KANBAN`, `^ARTIFACT` | READY, WAITING |
| A2A-02 | Pipeline de especialistas | `^WORKFLOW`, `^CONTEXT` | WAITING |
| A2A-03 | Contexto y evidencias compartidas | `^KNOWLEDGE`, `^EVIDENCE` | READY |
| A2A-04 | Espera durable de una dependencia | Namespace de dominio, `^SCHEDULE` | HIBERNATE |
| A2A-05 | Movimiento de un agente entre nodos | `^MIGRATION`, `^STATE` | HALTED → READY |
| A2A-06 | Failover de un agente caído | `^PRESENCE`, `^MIGRATION` | HIBERNATE/DEAD |
| A2A-07 | Descubrimiento y enrutado por capacidad | `^CAPABILITY`, `^PRESENCE` | WAITING |
| A2A-08 | Respuesta autónoma a incidentes | `^INCIDENT`, `^EVIDENCE` | READY/BLOCKED |

Los Namespaces de dominio de esta tabla son convenciones de aplicación; no
invaden los Namespaces reservados de MVM descritos en `spec-m-agent.md`.

## 4. A2A-01 — Kanban o campaña compartida entre agentes

### Objetivo

Varios agentes organizan y ejecutan una campaña sin un coordinador humano. Un
planner descompone el objetivo, workers especializados reclaman tareas y un
reviewer acepta o devuelve resultados.

### Árbol compartido

```text
^KANBAN(space,"meta")                         = {goal, policy, created_by}
^KANBAN(space,"member",agent_id)              = {capabilities, node_id}
^KANBAN(space,"task",task_id,"spec")         = {kind, input_refs, acceptance}
^KANBAN(space,"task",task_id,"status")       = READY|CLAIMED|WAITING|REVIEW|DONE|FAILED
^KANBAN(space,"task",task_id,"lease")        = {owner_agent, owner_node, epoch, expires_at}
^KANBAN(space,"task",task_id,"dependency",n) = other_task_id
^KANBAN(space,"task",task_id,"result_ref")   = ["ARTIFACT",space,artifact_id]
^KANBAN(space,"event",seq)                    = {type, task_id, agent_id, epoch, ts}
^KANBAN(space,"dedupe",idempotency_key)       = {event_seq, result_ref}
^ARTIFACT(space,artifact_id)                   = {mime, hash, body_or_uri}
```

### Flujo máquina a máquina

1. `planner-7` escribe el grafo de tareas y publica `task.ready`.
2. `researcher-2` recibe la referencia, comprueba dependencias y solicita el
   lease de `T-18` al nodo autoritativo.
3. Tras obtener `epoch=3`, cambia el estado a `CLAIMED` y ejecuta la tarea.
4. Si necesita `T-12`, deja `T-18` en `WAITING` y su Job en `WAITING`; no hace
   polling activo.
5. El agente que termina `T-12` escribe su resultado y envía
   `dependency.ready` al mailbox de `researcher-2`.
6. `researcher-2` vuelve a validar el Namespace, genera un artefacto y mueve
   `T-18` a `REVIEW` usando el mismo `epoch`.
7. `reviewer-4` verifica los criterios. Escribe `DONE` o crea una nueva revisión
   con una clave idempotente diferente.
8. El planner deriva nuevas tareas leyendo eventos y resultados; no depende de
   una pantalla ni de una acción humana.

### Invariantes

- Una tarea solo tiene un lease vigente.
- Un resultado sin el `epoch` vigente nunca pasa a `DONE`.
- Una dependencia se referencia; no se copia dentro de cada tarea.
- Reprocesar `task.ready` no crea otra tarea ni otro efecto.
- La campaña termina cuando todas las tareas terminales alcanzan `DONE` o una
  política autónoma determina `FAILED` definitivo.

## 5. A2A-02 — Pipeline de agentes especialistas

### Objetivo

Un agente de entrada pasa trabajo a agentes especializados —por ejemplo,
clasificador, recuperador, sintetizador y verificador— sin encadenar llamadas
síncronas frágiles.

### Flujo

1. El router crea `^WORKFLOW(run_id,"step",step_id)` con entradas expresadas
   como referencias a `^CONTEXT`.
2. Publica `step.ready` dirigido a `capability:classify`.
3. El agente elegido reclama el step mediante lease, escribe el resultado y
   publica `step.completed`.
4. Los siguientes agentes se despiertan cuando todas sus dependencias están
   completas.
5. El verificador escribe un veredicto reproducible con las referencias exactas
   de entrada y salida.

### Por qué usar Namespace + mailbox

El Namespace conserva el DAG y permite reanudarlo después de un reinicio. El
mailbox reduce latencia, pero cualquier agente puede recuperar trabajo pendiente
recorriendo `^WORKFLOW(run_id,"step",...)` con `$ORDER`.

## 6. A2A-03 — Memoria y evidencias compartidas

### Objetivo

Agentes en máquinas distintas construyen una base de hechos común sin enviarse
prompts o documentos completos en cada mensaje.

```text
^KNOWLEDGE(space,"fact",fact_id)       = {claim, source_refs, confidence, hash}
^KNOWLEDGE(space,"relation",rel_id)    = {from, predicate, to}
^EVIDENCE(space,"source",source_id)    = {uri, content_hash, observed_at}
^EVIDENCE(space,"chunk",source_id,n)   = {text_or_blob_ref, embedding_ref}
^KNOWLEDGE(space,"revision",fact_id,n) = {agent_id, previous_hash, change, reason}
```

Un recolector publica evidencias; un extractor crea hechos; un crítico añade una
revisión o contradicción; un agente de decisión consume solo hechos cuya política
de confianza sea suficiente. Los mensajes contienen `fact_id` o `source_id`.

La clave de deduplicación es el hash del contenido normalizado más el tipo de
operación. Una revisión nunca sobrescribe silenciosamente su procedencia.

## 7. A2A-04 — Hibernación hasta que exista información necesaria

### Objetivo

Un agente suspende procesamiento durante segundos, horas o días mientras otro
agente o nodo produce un dato necesario.

### Flujo

1. El Job guarda `wait_for={namespace,ref,min_version}` en su estado de dominio.
2. Solicita hibernación a la MVM; esta registra el límite en `^SCHEDULE` y pasa
   el Job a `HIBERNATE`.
3. El productor escribe el dato y envía `fact.available` con su referencia.
4. El nodo propietario despierta el Job antes del timeout. Si no llega el aviso,
   `^SCHEDULE` lo despierta para reevaluar la condición.
5. El Job lee la versión actual. Si aún no cumple `min_version`, renueva la
   espera; si la cumple, continúa desde su estado persistido.

El timeout no implica fracaso: es una oportunidad durable de reevaluación. La
condición está en datos y por eso sobrevive a reinicios y mensajes perdidos.

## 8. A2A-05 — Movimiento de un agente entre nodos

### Objetivo

Mover una ejecución desde `node-a` a `node-b` por afinidad de datos, coste,
capacidad disponible o mantenimiento, sin repetir las instrucciones ya
ejecutadas.

### Protocolo de migración segura

```text
^MIGRATION(run_id,"request")  = {source, target, reason, requested_at}
^MIGRATION(run_id,"lease")    = {owner_node, epoch, expires_at}
^MIGRATION(run_id,"snapshot") = {hash, state_ref, code_ref, data_cursors}
^MIGRATION(run_id,"status")   = PREPARE|TRANSFERRED|IMPORTED|COMMITTED|ABORTED
^MIGRATION(run_id,"ack")      = {target_pid, target_node, epoch, snapshot_hash}
```

1. `node-a` pasa el Job a `HALTED` en un punto cooperativo y deja de renovarle
   el lease de ejecución.
2. Exporta VM state, gas, mailbox y `wake_at`; calcula `snapshot_hash`.
3. DDP replica el snapshot y los Namespaces de datos necesarios a `node-b`.
4. `node-b` verifica hash, versión y capacidades, adquiere un nuevo
   `lease.epoch` e importa el estado con un PID local nuevo.
5. Si el Job estaba en `HIBERNATE`, `node-b` rearma el tiempo restante. Si estaba
   en `WAITING`, conserva el mailbox y la condición de espera.
6. `node-b` publica el ack y solo entonces pasa la migración a `COMMITTED`.
7. `node-a` invalida su copia. Puede conservar el snapshot para auditoría, pero
   nunca volver a ejecutarlo con un `epoch` anterior.

### Regla crítica

Exportar/importar ya existe en la MVM. La coordinación completa de `HALTED`,
lease, fencing, transferencia DDP y ack es un protocolo de orquestación que debe
implementarse encima. Copiar `^STATE` sin ese protocolo puede ejecutar el mismo
agente en dos nodos.

## 9. A2A-06 — Failover después de perder un nodo

### Objetivo

Reanudar en otro nodo un agente cuyo nodo dejó de emitir pulso.

### Flujo

1. Cada nodo publica en `^PRESENCE(node_id)` un heartbeat con expiración.
2. El supervisor agente detecta que el heartbeat y el lease de ejecución han
   vencido. No toma control antes de ambos vencimientos.
3. Selecciona el último snapshot confirmado y el cursor DDP asociado.
4. Concede un `epoch` mayor al nodo de reemplazo.
5. El reemplazo importa, reevalúa cualquier efecto pendiente mediante su clave
   idempotente y continúa.
6. Si el nodo antiguo reaparece, observa que su `epoch` es obsoleto y se
   auto-detiene.

El objetivo de recuperación es **at-least-once sin efectos duplicados**, no
exactly-once mágico. La idempotencia convierte el reintento en una operación
segura.

## 10. A2A-07 — Descubrimiento y enrutado por capacidad

### Objetivo

Un agente encuentra automáticamente otro agente capaz de ejecutar una tarea en
un nodo adecuado.

```text
^CAPABILITY(agent_id,"offer",capability) = {version, constraints, cost, ttl}
^PRESENCE(agent_id)                       = {node_id, load, status, heartbeat_at}
^ROUTING(request_id)                      = {required, input_ref, policy, status}
```

El router filtra ofertas no expiradas, valida que el agente pueda leer los
Namespaces de entrada y puntúa localidad, carga y coste. Emite una concesión con
TTL; si no recibe ack, concede a otro candidato usando un `epoch` superior.

No se deben anunciar secretos en `^CAPABILITY`. La oferta declara nombres de
capacidades; la autorización real la decide el macaroon entregado para ese
`request_id`.

## 11. A2A-08 — Respuesta autónoma a incidentes

### Objetivo

Agentes de observación, diagnóstico y reparación coordinan una incidencia entre
máquinas sin que un único proceso de larga duración concentre todo el contexto.

### Flujo

1. El detector crea `^INCIDENT(id,"observation",n)` con evidencia inmutable.
2. El agente de correlación agrupa observaciones y crea hipótesis.
3. Agentes de diagnóstico reclaman hipótesis distintas en paralelo.
4. El agente de política selecciona una acción permitida y emite un macaroon
   limitado al Namespace y a la duración de la reparación.
5. El reparador registra `intent`, `epoch` e `idempotency_key` antes del efecto.
6. Un verificador independiente compara métricas posteriores y marca
   `RESOLVED`, `ROLLBACK` o `ESCALATE_TO_AGENT`.

`ESCALATE_TO_AGENT` significa delegar a otro agente con más capacidad o permisos,
no solicitar intervención humana. Las acciones irreversibles siguen requiriendo
una política de autorización explícita definida por la red de agentes.

## 12. Criterios de conformidad para estos casos

Una implementación A2A se considera válida cuando demuestra:

1. dos nodos comparten un Namespace y recuperan el mismo árbol lógico;
2. repetir un lote DDP no duplica tareas, eventos ni efectos externos;
3. un mensaje duplicado solo provoca una relectura idempotente;
4. un Job en `HIBERNATE` no consume slices y conserva su `wake_at` al migrar;
5. un Job importado mantiene IP, frames, variables, mailbox y gas;
6. dos nodos que creen ser propietarios no pueden publicar ambos con éxito
   porque solo el `epoch` vigente es aceptado;
7. un nodo restaurado con un lease antiguo se auto-detiene;
8. un agente solo puede leer o escribir el subárbol autorizado por su macaroon;
9. perder el mailbox no pierde el trabajo, porque el Namespace permite
   reconstruirlo;
10. ningún flujo necesita una sesión, una pantalla o una decisión humana para
    progresar hasta su estado terminal.

## 13. Qué está disponible y qué falta cerrar

| Capacidad | Estado actual |
|-----------|---------------|
| Globals jerárquicos, `$ORDER`, transacciones y `$LOCK` | Implementado |
| Journal DDP con `seq`, cursores, reintento y anti-bucle | Implementado |
| Macaroons por Namespace y operación | Implementado |
| Mailbox durable y despertar de `WAITING` | Implementado |
| `HIBERNATE`, `^SCHEDULE` y restauración del tiempo restante | Implementado |
| Export/import del estado MVM | Implementado |
| Convención del sobre A2A e idempotency keys | Contrato propuesto aquí |
| Router `agent_id → node_id → pid` sobre `^PRESENCE` | Pendiente de orquestador |
| Lease autoritativo y fencing entre nodos | Pendiente de orquestador |
| Migración DDP coordinada con ack y rollback | Pendiente de orquestador |
| Conformance multi-nodo de los diez criterios anteriores | Pendiente |

La siguiente pieza de producto no es otra interfaz para personas: es el
orquestador A2A que convierte las primitivas ya existentes en ownership,
hibernación y migración seguras entre máquinas.
