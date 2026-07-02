# ROADMAP MVM Agent — Autonomía para Agentes Cognitivos

> **Visión**: Convertir MVM de motor batch a plataforma reactiva donde los procesos
> sean autónomos, se comuniquen bidireccionalmente con el agente, y reaccionen
> a cambios en datos sin intervención externa.

## Prioridad

| OBJ | Feature | Impacto | Depende de |
|-----|---------|---------|------------|
| **OBJ-101** | MVM Scheduler — HIBERNATE + auto-wake | 🔥 Crítico | — |
| **OBJ-102** | Agent Outbox — MVM → agente push | 🔥 Crítico | OBJ-101 |
| **OBJ-103** | Reactividad — triggers spawn MVM | 🔥 Crítico | OBJ-101 |
| OBJ-104 | Structured Mailbox — JSON nativo | ✨ Calidad | — |
| OBJ-105 | LLM Worker Pool — contexto reutilizado | ✨ Calidad | OBJ-101 |

---

## OBJ-101 — MVM Scheduler

**Qué**: Procesos MVM pueden dormirse y despertarse solos.

- Nuevo estado: `HIBERNATE`
- `^SCHEDULE(pid, wake_timestamp)` persistente en PDB
- `tick_all()` revisa ^SCHEDULE y mueve HIBERNATE→READY cuando toca
- M code: `S ^SCHEDULE(job_id, now+300)=1` para dormir 5 min
- Tool: `pdb_mvm_sleep(pid, seconds)` — helper del agente
- Tool: `pdb_mvm_wake(pid)` — despertar manual

**Archivos a modificar**: `mvm.py`, `pdb_tools.py`
**Tests**: 5-7 tests unitarios

## OBJ-102 — Agent Outbox

**Qué**: MVM puede dejar mensajes estructurados que el agente lee.

- `^AGENT_OUTBOX(msg_id)` con: pid, timestamp, type, payload, priority
- Tool: `pdb_mvm_outbox(limit=10)` — el agente lee mensajes pendientes
- Tool: `pdb_mvm_outbox_ack(msg_id)` — marcar como leído
- M code: escribir a ^AGENT_OUTBOX directamente desde dentro de MVM
- Alert system: priority=high genera mensaje "urgente" para el agente

**Archivos a modificar**: `mvm.py`, `pdb_tools.py`
**Tests**: 4-5 tests

## OBJ-103 — Reactividad (MVM Triggers)

**Qué**: Cambios en ^GLOBAL pueden spaw near/wake procesos MVM.

- Nueva acción de trigger: `spawn_mvm` — spawn ea MVM process
- Nueva acción: `signal_process` — despierta un proceso HIBERNATE en específico
- Pattern matching en subs: `^TASKS(*, status)` dispara en cualquier status
- El scheduler y los triggers trabajan juntos: trigger spawnea, scheduler gestiona el ciclo de vida

**Archivos a modificar**: `mvm.py`, `pdb_tools.py` (trigger system)
**Tests**: 4-5 tests

## OBJ-104 — Structured Mailbox

**Qué**: Mailbox admite JSON nativo, no solo strings.

- `pdb_mvm_mailbox_send(pid, message, type="text|json")`
- El field `type` indica si es string plano o struct
- Si type=json, el receptor lo recibe parseado automáticamente

**Archivos a modificar**: `mvm.py` (MailboxDevice), `pdb_tools.py`
**Tests**: 3 tests

## OBJ-105 — LLM Worker Pool

**Qué**: Device 77 mantiene contexto entre calls.

- Worker que no se destruye tras cada READ, espera nueva WRITE
- Pool de 1-3 workers reutilizables
- Timeout de inactividad (ej: 60s) antes de cleanup
- Compatible con HIBERNATE para workers en espera

**Archivos a modificar**: `mvm.py` (LLMDevice/LLMWorker)
**Tests**: 4 tests
