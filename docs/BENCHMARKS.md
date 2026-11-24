# M-Light v2 — Performance Benchmarks

## M-Light Rust v3 — Fase 5 (2026-07-15)

Apple Silicon arm64, macOS 15.7.7, Python 3.14.6, build Rust `--release`.
Las cifras Rust incluyen ctypes, JSON request/response y allocation de
strings; son el coste observable desde Python, no un benchmark nativo ideal.

| Escenario | Python mediana | Rust FFI mediana | Lectura |
|-----------|----------------:|-----------------:|---------|
| compilar 1 línea | 1,291 µs | 2,208 µs | domina la frontera FFI |
| compilar 4 líneas | 4,542 µs | 3,500 µs | Rust 1,30× más rápido |
| compilar + ejecutar 4 líneas | 8,250 µs | 10,708 µs | JSON domina script diminuto |
| ejecutar 4 líneas precompiladas | 4,250 µs | 12,083 µs | se reenvía bytecode JSON completo |
| FOR 1→100 | 269,875 µs | 67,959 µs | Rust **3,97× más rápido** |

Conclusión: el port ya gana cuando hay trabajo real dentro del VM. En scripts
de 1-4 instrucciones la ABI JSON cuesta más que la ejecución; Fase 6 elimina
esa copia en Jobs manteniendo handles/programas residentes en el scheduler.
SQLite no participa en esta medición y continúa como almacenamiento canónico.
Raw reproducible: `implementations/rust/lumen-m-light/benchmark_rust_vs_python.json`.

## MVM Tokio — Fase 6 (2026-07-15)

Mismo Apple Silicon y misma SQLite vía `pdb_tools` para ambos schedulers.
Workload: 50 Jobs de 5 SET locales, 50 mensajes durables y restore de 100
Jobs. No es un benchmark de VM puro: mide deliberadamente persistencia.

| Escenario | Python | Rust Tokio | Lectura |
|-----------|-------:|-----------:|---------|
| spawn | 1.362 Jobs/s | 1.347 Jobs/s | equivalentes (Rust -1,1%) |
| tick completo | 1.376 Jobs/s | 1.365 Jobs/s | equivalentes (Rust -0,8%) |
| mailbox durable | 20.495 msg/s | 3.959 msg/s | Python legacy no deja READ en WAITING; no son garantías equivalentes |
| restore 100 Jobs | 10,76 ms | **4,16 ms** | Rust 2,58× más rápido |

La cifra de mailbox no es un speedup objetivo ni una comparación semántica
perfecta: el scheduler Python actual termina el Job ante READ vacío en ese
workload, mientras Rust persiste el mensaje y la transición WAITING→READY.
La conclusión útil es que el callback/SQLite, no Tokio ni el bytecode, domina
Jobs diminutos. Raw reproducible:
`implementations/rust/lumen-mvm/benchmark_tokio_vs_python.json`.

**Date:** 2026-07-12
**Environment:** Python 3.11, Windows 10, AMD Ryzen

## PDB storage — SQLite WAL (added 2026-07-14, macOS/Apple Silicon)

Tras centralizar PRAGMAs en `_apply_pragmas()` (WAL + synchronous=NORMAL +
mmap 256MB). BD scratch sin triggers/índices; un commit por SET como hace
`tool_set`.

| Escenario | Resultado |
|-----------|-----------|
| SQL crudo, journal DELETE (antes) | 5.066 SET/s |
| SQL crudo, journal WAL (ahora) | 88.696 SET/s (~18×) |
| `tool_set` API, sin lectores | 21.359 SET/s |
| `tool_set` API, sostenido 6s con 3 lectores concurrentes | **15.212 SET/s, 0 errores** |
| 3 lectores (`tool_get`+`tool_order`) durante escritura sostenida | ~22.000 ops/s cada uno, **0 `database is locked`** |

Referencia pre-WAL en producción: ~115-130 SET/s (bloqueo escritor↔lectores).
El salto real de la API es ~120×. WAL es persistente en el fichero de BD:
las conexiones que no tocan el pragma lo heredan automáticamente.

## Micro-operations (microseconds)

| Operation | Time (μs) | Description |
|-----------|-----------|-------------|
| compile (1 line) | 5.6 | `S x=42 W x Q` |
| compile (4 lines) | 16.4 | `S x=42` `S y=x+1` `W y` `Q` |
| SET x=42 + exec | 17.4 | Single variable assignment |
| SET + arithmetic (3 ops) | 11.4 | `S x=10 S y=x+5 S z=x*y` |
| `$P("a,b,c",",",2)` | 8.4 | Piece extraction → "b" |
| `$E("hello",3,7)` | 12.3 | Extract substring → "llo w" |
| `$TR("hello","aeiou","-----")` | 24.4 | Character translation |

## Native engine — sin frontier (added 2026-11-24)

Las cifras de arriba incluyen ctypes + JSON + allocation (lo que ve Python). Esta
tabla mide el **motor solo**: `Compiler::compile` y `Vm::run` en Rust puro, sin
FFI ni serialización. Banco: `tests/bench_nativo.rs`
(`cargo test --release --test bench_nativo -- --nocapture`).

**Entorno: Lenovo L13, Intel i7-10510U (4C/8T, 1,80 GHz base), 15,7 GB RAM con
13,3 GB ocupados.** 20.000 iteraciones por caso, **5 pasadas midiendo la CPU
antes y después de cada una**. Se publica mediana y rango, no el mejor caso.

| Operation | p50 mediana (µs) | rango entre pasadas (µs) |
|-----------|-----------------:|-------------------------:|
| compile (1 línea) | **3,6** | 2,0 – 4,9 |
| compile (4 líneas) | 8,3 | 4,6 – 11,1 |
| ejecutar 1 asignación | **4,6** | 3,4 – 7,6 |
| aritmética | 2,3 | 2,2 – 5,0 |
| `$ORDER` | 7,0 | 6,0 – 11,4 |
| bucle 100 iteraciones | **268** | 203 – 469 |

**La correlación con la carga es directa y sirve de control:**

| pasada | CPU antes → después | compile 1 línea |
|--------|--------------------|----------------:|
| 5 | 13,6 % → 18,8 % | **2,0 µs** |
| 1 | 19,5 % → 82,0 % | 2,3 µs |
| 3 | 60,9 % → 81,1 % | 3,6 µs |
| 2 | 95,7 % → 52,7 % | **4,9 µs** |

### Motor nativo frente a frontera FFI

Medido en la misma sesión, bajo la misma carga — por eso la **relación** es
fiable aunque las cifras absolutas dependan de la máquina:

| | nativo | vía Python | factor |
|---|---:|---:|---:|
| compile 1 línea | ~2–5 µs | ~14–27 µs | **~6×** |
| ejecutar 1 asignación | ~3–6 µs | ~92–174 µs | **~18×** |
| `$ORDER` | ~6–11 µs | ~100–178 µs | **~18×** |

**El cuello de botella es la frontera con Python, no el motor.** Un servicio
escrito en Rust está en la columna izquierda.

### ⚠️ Cómo leer estas cifras

- **Solo el L13 está medido.** Cualquier otra máquina es estimación.
- **No se puede afirmar «sub-microsegundos»**: el mínimo medido es 2,0 µs y el
  mínimo estimado en un Apple M2 Pro sería ~1,4 µs. Ningún escenario baja de 1 µs.
- **No se puede afirmar «p99.99»**: la profundidad máxima medida es p99.9.
- Para publicar una cifra de otra máquina: medirla allí, con frecuencia fija y
  3–5 pasadas.

Estado por afirmación, con lo que está y lo que no: [`ESTADO-REAL-POR-AFIRMACION.md`](ESTADO-REAL-POR-AFIRMACION.md).

## Script-level operations (milliseconds)

| Operation | Time (ms) | Description |
|-----------|-----------|-------------|
| FOR 1→100 loop | 2.31 | `F i=1:1:100 S t=t+i` (100 iterations) |
| DO ^script | 104.5 | First call (module load + compile + exec) |
| DO ^script (with bytecode cache) | ~5 | Second call (cache hit, no recompile) |
| DO ^script with args | 111.7 | `$1`, `$2` parameters |

## Cloud DDP (milliseconds)

| Operation | Time (ms) | Notes |
|-----------|-----------|-------|
| DDP health check | 154 | Cloudflare cold-start dominated |
| DDP status | 156 | Cloudflare cold-start dominated |

## Key observations

1. **Compile is fast** — 5-16 μs for typical scripts
2. **$functions are fast** — 8-24 μs (pure Python, no regex)
3. **FOR loop** — 2.3ms for 100 iterations = ~43,000 iterations/sec
4. **DO ^script overhead** — dominated by Python module imports (~100ms). Bytecode cache reduces to ~5ms
5. **DDP cloud** — latency is Cloudflare cold-start (150+ms); warm requests would be <20ms

## Comparison with Python eval()

| Operation | M-Light v2 | Python eval() | Slowdown |
|-----------|------------|---------------|----------|
| Variable assignment | 17 μs | ~0.1 μs | ~170x |
| String function ($P) | 8 μs | ~0.5 μs | ~16x |
| FOR 100 iterations | 2.3 ms | ~0.3 ms | ~8x |
| Full script call | 104 ms | ~1 ms | ~100x |

The slowdown is expected — M-Light is a full interpreted MUMPS VM with dispatch tables, opcode handlers, and function tables. Python eval() is native C.

## Real-world impact

- **Script compilation**: imperceptible (< 0.1ms)
- **Data operations** (SET, GET, KILL): imperceptible (μs)
- **String processing** ($P, $E, $TR): 8-24 μs — no human noticeable
- **DDP sync**: 150ms cloud → dominated by network, not VM
- **DO ^script**: 5ms with cache — fast enough for agent automation
