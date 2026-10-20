# ADR-001 — `lumen_tasks` como proyección separada de `tasks`

**Fecha:** 2026-10-19 · **Estado:** aceptada
**Decisión de:** Gonzalo
**Ámbito:** `cadences.app` (`ProjectOS`) × nodos LUMEN/Hermes

---

## Contexto

`cadences.app` ya tiene `projects` y `tasks` (con `version` para CAS). El endpoint
`/api/nodes/sync` necesitaba un sitio donde los nodos LUMEN/Hermes dejaran su
trabajo. Dos opciones:

| Opción | Descripción |
|---|---|
| **A — Unificar** | Los nodos leen y escriben directamente en `tasks` |
| **B — Proyección separada** | Los nodos usan `lumen_tasks`, y una capa sincroniza |

## Decisión

**Se adopta B: proyección separada, hasta que el modelo madure.**

---

## Motivos (concretos, no genéricos)

1. **`tasks` es del front, con sus reglas.** Tiene `customerId`, `assignedTo`,
   `checklist`, `attachments`, `comments`, `estimatedTime`, `data`… Un nodo que
   escriba directo tiene que cumplir **todas** esas invariantes, incluidas las
   que solo existen en la UI.

2. **Un cambio de esquema del front rompería a los nodos en silencio.** Con la
   proyección, el **endpoint es el único contrato**: cambia el front, se adapta
   la sincronización, los nodos no se enteran.

3. **El nodo no necesita el 100% del modelo.** Necesita: título, spec, estado,
   prioridad, versión y a quién está asignada. `lumen_tasks` tiene exactamente eso
   (más `parent_id`), y nada más.

4. **Los eventos son append-only y no tienen sitio en `tasks`.** `lumen_events`
   guarda historia, checkpoints y resultados con `artifact_ref/hash` sin tocar el
   modelo del front.

5. **Reversible y barato.** Si un día se unifica, la proyección ya tiene los datos
   y el histórico de eventos sirve para migrar.

## Consecuencias

### A favor
- El contrato nodo ↔ cadences es **uno solo** y explícito.
- Cambios de la UI no rompen nodos.
- El `lease` y el `event log` viven fuera del modelo del front (no lo ensucian).

### En contra (asumido)
- **Hay dos sitios donde vive una tarea.** Es la desventaja real: `tasks` (usuario)
  y `lumen_tasks` (nodo) pueden divergir.
- **Mitigación obligatoria:** la sincronización entre ambas es **el siguiente
  paso**, no un "ya veremos". Sin ella, la divergencia es cuestión de tiempo.
- Los usuarios no ven el trabajo de los nodos hasta que esa capa exista.

## Lo que NO se decide aquí

- **Quién manda si divergen.** Debe ser `tasks` (el usuario manda) con los
  cambios del nodo propuestos como evento, nunca escritura silenciosa.
- **Cuándo se unifica.** Criterio propuesto: cuando los nodos operen sobre
  tareas reales durante un periodo sin incidentes de divergencia.

## Referencias

- `docs/ARQUITECTURA-capas-politica-autoridad.md` (estudio): owner por namespace.
- `docs/06-nodos-autonomos-gestion-central.md` (estudio): el centro proyecta, no manda.
- `migrations/lumen-002-project-task-lease.sql`: el esquema de la proyección.
- `functions/api/nodes/sync.js`: el contrato (register/pull/push/lease/release).
