# Estado real por afirmación — LUMEN

> Documento vivo. Cada fila es una afirmación que **aparece en material público
> o en los documentos de especificación**, con su estado comprobado contra el
> repo. La regla: si algo está en la columna «NO IMPLEMENTADO», no se puede
> presentar como característica del producto.

**Última verificación:** 24-nov-2026 · repo `lumen-protocol` · 120 ficheros `.rs`
escaneados + tests ejecutados.

## Cómo leer esta tabla

| Estado | Significa |
|---|---|
| ✅ **VERIFICADO** | Implementado y con test o medición que lo respalda |
| 🟡 **PARCIAL** | Existe, pero con límites que hay que decir al contarlo |
| 🔵 **DISEÑO** | Documentado, no implementado. Se puede presentar como hoja de ruta |
| ❌ **NO EXISTE** | Afirmado en algún sitio y no hay código. **No usar en material público** |

---

## Núcleo de ejecución

| Afirmación | Estado | Evidencia |
|---|---|---|
| Máquina virtual M (MVM) que ejecuta código M | ✅ VERIFICADO | `lumen-mvm` + `lumen-m-light/src/vm.rs` (5.083 líneas) |
| Portabilidad nativa (Windows/Linux, 32/64 bits, ARM) | ✅ VERIFICADO | targets `i686-unknown-linux-musl`, `x86_64-unknown-linux-gnu`, `armv7-unknown-linux-musleabi`, `lumen_mlight.dll` + `liblumen_mlight.so` |
| WebAssembly (navegador) | ✅ VERIFICADO | target `wasm32-unknown-unknown`, demo en producción con 22 agentes |
| Procesos persistentes (spawn, tick, mailbox, kill, sobrevivir reinicio) | ✅ VERIFICADO | `lumen-mvm`, docs/COGNITIVE_OS.md |
| Fibras con espera sin bloquear | ✅ VERIFICADO | `fiber_await.rs` |
| **Sin garbage collector** | 🟡 **PARCIAL** | Es cierto **porque está en Rust**, no por un diseño de memoria propio. Decirlo así: «sin GC porque no hay runtime gestionado» |
| **Asignación por regiones (arenas)** | ❌ **NO EXISTE** | Cero apariciones de `arena`/`bumpalo` en 120 `.rs`. Los `pool` del código son **thread pools**, no memoria |
| **Memoria zero-copy MVM↔LMDB** | ❌ **NO EXISTE** | `MemoryHost::from_lmdb` abre el store; no comparte layout ni punteros con la MVM |
| **Sin metering de gas** | ❌ **NO EXISTE** | Al contrario: `gas_limit` es parámetro real y obligatorio en `execute()` |
| JIT M→Rust | 🟡 PARCIAL | Existe `--jit` en `mvm-nas`, **experimental y desactivado por defecto** |

## Persistencia

| Afirmación | Estado | Evidencia |
|---|---|---|
| LMDB como motor embedded | ✅ **VERIFICADO** | `lmdb_store.rs` (880 líneas), `heed` 0.22, **14/14 tests verdes** (`cargo test --features lmdb --test lmdb_host`) |
| mmap sin precarga (arranque rápido con base grande) | ✅ VERIFICADO | arranque real: `· store LMDB directo (sin precarga)` |
| Persistencia tras cerrar y reabrir | ✅ VERIFICADO | test `roundtrip_y_persistencia` |
| Transacciones anidadas con rollback | ✅ VERIFICADO | test `transacciones_rollback_commit_anidado` |
| SQLite como alternativa | ✅ VERIFICADO | `storage=sqlite`, es el motor por defecto de `mvm-nas` |
| **LMDB como ÚNICO motor** | 🟡 PARCIAL | Es **opcional** (feature `lmdb`). Hay que compilarlo con la feature o usar el binario `mvm-nas` que la trae |
| B+ tree con Copy-on-Write | ✅ VERIFICADO | Pero es **propiedad de LMDB**, no implementación propia de LUMEN. Redactar como «LMDB aporta…» |
| Lectores lock-free (Single-Writer/Multiple-Readers) | ✅ VERIFICADO | Es el modelo de LMDB |
| Hot snapshots sin parar el sistema | ✅ VERIFICADO | `snapshot` en `ddp.rs` |
| 15 µs por GET | ✅ VERIFICADO | citado en `README.md` y `docs/PLAN_EVOLUCION.md` (58K GET/s, 27K insert/s) |
| Vectores/embeddings en la misma base | ✅ VERIFICADO | `$DEVICE("rag:embed")`, `docs/RAG-EMBEDDINGS.md`, medido 23/25 en híbrido |

## Distribución y seguridad

| Afirmación | Estado | Evidencia |
|---|---|---|
| DDP con sincronización por deltas | ✅ VERIFICADO | `ddp.rs`, `host.rs` |
| Transporte QUIC | ✅ VERIFICADO | `lumen-znet/tests/quic_e2e.rs` verde |
| ChaCha20-Poly1305 | ✅ VERIFICADO | `crypto.rs` |
| Macaroons con caveats | ✅ VERIFICADO | `tests_macaroon.py` ejecutado: **31/31 passed** (24-nov-2026) |
| Identidad por clave pública (Ed25519) | ✅ VERIFICADO | `tests/flota_pki.rs`, 6 tests |
| Offline-first / redes intermitentes | ✅ VERIFICADO | `mode=offline` |
| **Descubrimiento multicast** | ❌ **NO EXISTE** | `datagram.rs` tiene `join_multicast`, nadie lo usa (reconocido en ADR-002) |
| **NAT traversal / ICE-STUN** | ❌ **NO EXISTE** | ADR-002: `mode=wan` es **parcial**, QUIC funciona pero NAT no |
| **Consenso tipo blockchain (PoW/PoS)** | ❌ **NO EXISTE** | No hay código de consenso. DDP sincroniza estado, no consensúa |

## Capacidades de agente

| Afirmación | Estado | Evidencia |
|---|---|---|
| Un agente es una fila en `^PERSONALITY` | ✅ VERIFICADO | 18 campos reales en el esquema |
| Orquestación multi-agente (Smith) | ✅ VERIFICADO | `smith.rs` (1.000 líneas), demo en producción |
| 129 herramientas MCP | ✅ VERIFICADO | 4 servidores: filesystem 13, web 2, thinking 81, PDB 19 |
| Enrutado determinista sin tokens | ✅ VERIFICADO | recorrido ordenado sobre la tabla |

## Afirmaciones de latencia — ⚠️ leer antes de publicar

Medido con `bench_latencia.py` (24-nov-2026, AMD64, 2.000 iters, incluye frontera FFI):

| Operación | p50 | p99 | p99.9 |
|---|---|---|---|
| compilar 1 línea | 24,8 µs | 71,8 µs | 138,4 µs |
| compilar 4 líneas | 25,6 µs | 109,9 µs | 302,4 µs |
| ejecutar 1 asignación | 173,9 µs | 740,1 µs | 7.504,8 µs |
| aritmética | 179,3 µs | 545,8 µs | 1.595,1 µs |
| bucle 100 iteraciones | 840,8 µs | 2.199,7 µs | 6.667,5 µs |
| global set+get | 207,7 µs | 585,1 µs | 1.245,0 µs |
| `$ORDER` | 164,4 µs | 437,8 µs | 620,0 µs |

**Lo que NO se puede afirmar:**

- ❌ **«sub-microsegundos»** — los papers de HFT lo dicen. La medición está entre
  25 µs y 2,2 ms. Diferencia de 3 a 300×.
- ❌ **«p99.99»** — no hay ninguna medición con esa profundidad de cola.
  Lo máximo medido es p99.9, y con `iters` alto.
- ❌ **«jitter despreciable»** — el jitter (p99−p50) medido va de **47 µs a 1.359 µs**.
  El propio banco lo cuantifica para poder mejorarlo.
- ✅ **«latencia de cola medida»** — esto sí, con p50/p95/p99/p99.9 y muestra real.

## Correcciones a documentos anteriores

- **«Lightweight Universal *Marine* Enterprise Network»** y
  **«Lightweight Ubiquitous *Mesh* Execution Network»** conviven en la misma
  carpeta de papers: son **dos expansiones distintas de la misma sigla**. Elegir una.
- Los dos `.docx` «Especificación Técnica» (normal y «V2») son **idénticos en
  texto**; la V2 no cambia nada.

---

## Cómo mantener esto

Al añadir una capacidad nueva al material público, **añadir su fila aquí primero**.
Si no se puede rellenar la columna «Evidencia» con un fichero, un test o una
medición, entonces el estado es 🔵 DISEÑO o ❌ NO EXISTE — y no se presenta como
característica.
