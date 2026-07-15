# M-Light Roadmap — MSM Compatibility Plan

> Actualizado 2026-07-15. Estado real verificado contra código y tests.
> Plan general: [PLAN_EVOLUCION.md](PLAN_EVOLUCION.md)

## ✅ OBJ-1: String Functions ($L, $F, $TR)
`$L(string)` → LENGTH · `$F(string,sub)` → FIND · `$TR(string,old,new)` → TRANSLATE

## ✅ OBJ-2: Variable Operations
KILL de locales · SET múltiple con coma (`S A=1,B=2`) · NEW (push/pop scope)

## ✅ OBJ-3: Numeric Operations
`+expr` casting · `#FF` hex literales · `\` división entera · `#` módulo

## ✅ OBJ-4: Control Flow
`G label` (GOTO) · `D label` (DO) con retorno · Labels multilínea · Call stack

## ✅ OBJ-5: I/O Operations
`W *n` (ASCII) · `?n` (column) · `R prompt:var` (READ) · `O`/`U`/`C` device · `N` (NEW)

## ✅ OBJ-6: PDB Cognitive Benchmark Demo
Benchmarks M-Light v2: compile 5μs, SET 17μs, DO ^script 104ms (commit edb2dca).

## ✅ v2: Compilador + Stack-VM (julio 2026)

- `pdb-sync/m_light_compiler.py` — compilador a bytecode
- `pdb-sync/m_stackvm.py` — stack-VM (VM_VERSION 2.0.0), error trap nativo
  ($ECODE/$ZERROR), OP_TABLE con binary search
- Bytecode cache en ^ROUTINE con invalidación SHA256 + VM_VERSION en cache key
- IMP-01..05: WRITE, aritmética, ^global PDB, DO subrutinas, FOR+$O loop

## ✅ Superficies de ejecución (julio 2026)

- **API HTTP**: `POST localhost:8081/vm/execute` (`vm_api.py`) — scripts M
  vía HTTP para Zalo, Lisa, Tom, Angi
- **Consola web**: `m_console.py` (8084/8085) — terminal + WebSocket, sesión
  persistente, ZW tree, ZR list, ZJOB, ZW de locales, /ai coder
  (CONSOLE-05: 18/18)
- **Dashboards**: D ^SS, D ^GS, D ^%SS nativo con datos reales de PDB
  (salud ecosistema, namespaces, MVM, agents, servicios, storage, cron)
- **REPL**: pdb_m_repl multilínea
- **MVM**: `mcp-servers/pdb/mvm.py` — scheduler cooperativo, estados
  READY→DEAD, mailboxes ($IO 99), gas por tick, persistencia en ^STATE

## ✅ Runtime dispatch MSM (julio 2026)

- Stub inteligente $VIEW(41) con valores realistas
- Traceo del bytecode executor de MSM confirmado vía Ghidra: ZFUNCS es tabla
  runtime en .rdata (VA 0x004bebea), no funciones independientes
- Doc: `mcp-servers/pdb/references/zfuncs-runtime-dispatch.md`

## ✅ v3: Port Rust (Fase 5, julio 2026)

- `rust/lumen-m-light`: bytecode SHA256 + stack-VM resumible, C ABI JSON.
- `@` local/global en lectura y escritura; TSTART/TCOMMIT/TROLLBACK.
- Gas por slice y budget; frames FOR, call stack y scopes serializables.
- `lumen_mlight.py`: ctypes + snapshot/diff sobre SQLite vía `pdb_tools`.
- `MLIGHT_ENGINE=rust|python` (default Python durante la transición).
- Golden compartido de 8 programas + tests Rust/Python y benchmark raw.

## 🎯 Pendiente (Fase 6)

- Host SQLite live/callback bajo el scheduler Tokio para aislamiento entre
  ejecuciones concurrentes sobre las mismas claves.
- Jobs Tokio, mailboxes y persistencia/restore automático por tick.
- Ampliar golden con rutinas MSM reales y differential testing continuo.

## Lo que soporta M-Light ahora

- $GET/G, $DATA/D, $ORDER/O, $PIECE/P, $EXTRACT/E, $SELECT/S
- $LENGTH/L, $FIND/F, $TRANSLATE/TR
- SET (simple, comma-sep, global) · KILL (local y global)
- FOR (infinito y con rango) · IF/ELSE con bloques {}
- QUIT con postconditional · GOTO (G label), DO (D label) con call stack
- WRITE (W *n, W !, W ?n, W "text") · READ (R prompt:var)
- NEW, OPEN, USE, CLOSE
- Abreviaturas M ($O, $G, $D, $P, $E, $S, $L, $F, $TR)
- Hex literales (#FF = 255) · Aritmética left-to-right (\ div, # mod)
- +cast numérico · undefined=0 en aritmética (fix 414920d)
- Variables locales y globales ^ns(subs) · Comentarios ; inline
- $VIEW con emulación de memoria de sistema MSM
- MSM STU coverage: ~70% de sintaxis básica
