- $VIEW con emulación de memoria de sistema MSM
- MSM STU coverage: ~70% de sintaxis básica

---

## ✅ S1-S4: Rust Cognitive OS (Julio 2026)

> El roadmap original planificaba "Fase 5.1: PdbHost nativo" como trabajo futuro.
> Julio 2026: las 4 fases están completadas y en producción.

### S1 — PdbHost + Device 8/9 (completado)

- `RedbHost`: ^GLOBALS en Rust puro (redb), sin FFI Python
- `Device 8`: HTTP client nativo — `O 8:"GET url"` → reqwest async
- `Device 9`: Webhook server nativo — `O 9:":8767"` → axum
- `Opcode::Open` parsea device number y args
- Tests: persistencia post-crash, HTTP dispatch, webhook receive

### S2 — LlmEngine + PromptBuilder + ResponseParser (completado)

- `LlmEngine` trait + `HttpLlmEngine` (OpenAI API)
- `PromptBuilder v0.2`: ^GLOBALS → LLM prompt con límites $ORDER
- `ResponseParser`: ```m / ```tool / ```msg / texto
- `THINK_INTERNAL` hook interceptado en JobActor

### S3 — Tool Dispatch + WAITING (completado)

- `ToolDispatcher`: tool calls no bloqueantes vía mpsc channel
- `WAITING` state con back-off 100ms + mailbox wake-up
- Mailbox entre jobs: mensaje en WAITING → READY

### S4 — Agente Persistente (completado)

- `Agent Loop`: código M canónico (CHECK_MAILBOX → THINK → YIELD)
- `^PROCESSES`: jobs sobreviven reinicio, reanimación automática
- Tests end-to-end: webhook → mailbox → think → output

### Docs

- [ARCHITECTURE.md](../ARCHITECTURE.md) — capas, módulos, data flow, tests
- [AGENT_GUIDE.md](../AGENT_GUIDE.md) — construir tu primer agente
- [COGNITIVE_OS.md](COGNITIVE_OS.md) — visión general con stack Rust