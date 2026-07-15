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
de 1-4 instrucciones la ABI JSON cuesta más que la ejecución; Fase 6 puede
eliminar esa copia manteniendo handles/programas residentes en el scheduler.
SQLite no participa en esta medición y continúa como almacenamiento canónico.
Raw reproducible: `implementations/rust/lumen-m-light/benchmark_rust_vs_python.json`.

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
