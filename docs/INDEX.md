# ◆ Mapa de documentación LUMEN

> Actualizado: 2026-07-15. Sustituye a `doc-map-2026-06-20.md` (histórico).
> Regla: si tocas código que contradice un doc, actualiza el doc o márcalo aquí.

## Núcleo (empezar aquí)

| Doc | Qué es | Estado |
|-----|--------|--------|
| [PLAN_EVOLUCION.md](PLAN_EVOLUCION.md) | **Plan canónico** PDB + M-Light + MVM, fases y ROI | ✅ Vigente (2026-07-15) |
| [spec-m-agent.md](spec-m-agent.md) | **Spec normativa** subset M + globals + MVM + contrato (v0.2) | ✅ Vigente (2026-07-15) |
| [ROADMAP_MLIGHT.md](ROADMAP_MLIGHT.md) | Estado M-Light Python/Rust y pendientes Tokio | ✅ Vigente (2026-07-15) |
| `../ajustes.md` | Revisión del plan contra código real | ✅ Vigente (2026-07-14) |
| `../alternativas.md` / `../alternativa2.md` | Análisis de motores de almacenamiento (redb, LMDB, fjall...) | ✅ Vigente (2026-07-14) |
| [COGNITIVE_OS.md](COGNITIVE_OS.md) | Arquitectura del OS cognitivo, referencia de tools | Revisar tool-counts |
| [BENCHMARKS.md](BENCHMARKS.md) | Benchmarks consolidados | ✅ Vigente (2026-07-14) |

## Primers y arquitectura

| Doc | Qué es | Estado |
|-----|--------|--------|
| [PDB_PRIMER.md](PDB_PRIMER.md) | Introducción a PDB | Vigente (2026-07-14) |
| [LUMEN_PDB_PRIMER.md](LUMEN_PDB_PRIMER.md) | LUMEN + PDB juntos | Vigente (2026-07-14) |
| [pdb-first-architecture.md](pdb-first-architecture.md) | Arquitectura PDB-first | Junio 2026 |
| `../implementations/python/pdb-sync/SYSTEM_SCHEMA.md` | Schema del namespace ^System (pulse, decisions, identidad, gobernanza) | ✅ Vigente |
| `../implementations/mcp-servers/pdb/references/zfuncs-runtime-dispatch.md` | Traceo Ghidra del bytecode executor MSM | ✅ Vigente (2026-07-14) |

## Protocolo LUMEN (transporte)

| Doc | Qué es | Estado |
|-----|--------|--------|
| `../RFC_LUMEN.md` | RFC formal del protocolo | Vigente (2026-07-02) |
| `../SPEC_DEV.md` / `../SPEC_DEV_ES.md` | Spec para desarrolladores | Vigente (2026-07-02) |
| `../work.md` | **Backlog abierto del protocolo** (bindings, conformance, CI) — ámbito distinto al PLAN_EVOLUCION | Vigente (2026-07-02) |
| `../DICTIONARY.md` / `_ES` | Diccionario del protocolo | Junio 2026 |
| [lumen-universal-protocol-strategy.md](lumen-universal-protocol-strategy.md) | Protocolo como infraestructura | Junio 2026 |
| [lumen-ws-dashboard.md](lumen-ws-dashboard.md) | Dashboard WebSocket con frames LUMEN | Junio 2026 |

## Visión y paper

| Doc | Qué es | Estado |
|-----|--------|--------|
| `../PAPER.md` / `../PAPER_ES.md` | Paper académico | Junio 2026 |
| `../SOUL.md` | Manifiesto filosófico | Junio 2026 |
| `../README_EXT.md` | README extendido | Junio 2026 |

## Guías de uso

| Doc | Qué es | Estado |
|-----|--------|--------|
| `../INSTALL.md` / `_ES` | Instalación | Junio 2026 |
| `../HERMES_INTEGRATION.md` | Setup del agente Hermes | Junio 2026 |
| [lumen_thinking_usage.md](lumen_thinking_usage.md) | Uso del thinking server | Junio 2026 |
| `../skills/` | 20 skills (SKILL.md por directorio) | Variable |
| `../examples/` | Demos ejecutables | Junio 2026 |

## Históricos (no borrar, no actualizar)

| Doc | Qué es |
|-----|--------|
| [doc-map-2026-06-20.md](doc-map-2026-06-20.md) | Mapa de docs de junio — superseded por este INDEX |
| [enterprise-stress-testing-2026-06-20.md](enterprise-stress-testing-2026-06-20.md) + ref | Stress test "War Room" de junio |
| [token-efficient-tools-2026-06-20.md](token-efficient-tools-2026-06-20.md) | 5 tools token-efficient (junio) |
| `../revisions/` | Actas de revisión y auditorías |

## Deuda documental conocida (2026-07-15)

1. La suite pdb-sync (journal DDP, sync engine, consola, vm_api) solo está
   documentada en commits y docstrings — el PLAN_EVOLUCION §1 es ahora el
   resumen de referencia.
2. `COGNITIVE_OS.md` y `README.md` citan tool-counts de junio; verificar
   tras el cierre del contrato PDB (Fase 1b).
3. Terminología: "WAL" del equipo = journal DDP en ^CHANGES (pdb_journal.py),
   no el `journal_mode=WAL` de SQLite. Docs nuevos deben desambiguar.
