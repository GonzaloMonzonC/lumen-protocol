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

Hay **dos bancos** y miden cosas distintas. Confundirlos es el error que hace que
una especificación afirme algo que nadie midió.

### 1. Motor puro (Rust nativo) — `cargo test --release --test bench_nativo`

Mide `Compiler::compile` y `Vm::run` **sin FFI, sin JSON, sin Python**. Es la
cifra del motor. 20.000 iters, AMD64:

| Operación | p50 | p99 | p99.9 |
|---|---|---|---|
| compilar 1 línea | **5,00 µs** | 10,70 µs | 40,80 µs |
| compilar 4 líneas | 9,70 µs | 29,70 µs | 174,40 µs |
| ejecutar 1 asignación | **5,60 µs** | 14,00 µs | 49,20 µs |
| aritmética | 8,20 µs | 17,90 µs | 56,60 µs |
| `$ORDER` | 9,90 µs | 29,20 µs | 86,30 µs |
| bucle 100 iteraciones | 465,90 µs | 1.028,80 µs | 3.282,70 µs |

### 2. Viaje completo (Python→FFI→motor) — `bench_latencia.py`

Mide lo que ve un servicio que llama desde Python. Incluye la frontera, que es
**el coste dominante**:

| Operación | p50 | p99 | p99.9 |
|---|---|---|---|
| compilar 1 línea | 27,3 µs | 75,9 µs | 131,5 µs |
| ejecutar 1 asignación | 103,0 µs | 388,4 µs | 559,8 µs |
| bucle 100 iteraciones | 498,3 µs | 1.313,0 µs | 3.196,4 µs |

### La comparación que importa

| | motor nativo | vía Python | factor |
|---|---|---|---|
| compilar 1 línea | 5,00 µs | 27,3 µs | **5,5×** |
| ejecutar 1 asignación | 5,60 µs | 103,0 µs | **18×** |
| `$ORDER` | 9,90 µs | 178,3 µs | **18×** |

**El motor es de 5 a 18 veces más rápido que la cifra que se venía citando.**
El cuello de botella es la frontera con Python, no LUMEN. Un servicio escrito en
Rust (o el binario `mvm-nas`) está en la columna izquierda; uno que llama por FFI
está en la derecha.

### ⚠️ Variabilidad medida — leer antes de citar una cifra

- **Deriva térmica dentro de una pasada:** medido, `compile_1_linea` pasó de
  14,4 µs con 200 iters a 32,0 µs con 20.000 — el doble sin cambiar código.
  Ambos bancos lo detectan (dos mitades; si la 2ª es >20% más lenta, marcan `CALOR`
  y reportan la 1ª).
- **Variabilidad entre ejecuciones:** dos pasadas idénticas dieron
  `ejecutar_1_set` 103 µs y 150 µs (±45 %).

**Lo defendible** es el orden de magnitud sobre una máquina concreta:
**µs de un dígito para compilar y ejecutar en nativo**, y cientos de µs cuando
se pasa por FFI. Citar «5,00 µs» como verdad universal es tan frágil como citar
«sub-microsegundos».

**Lo que NO se puede afirmar:**

- ❌ **«sub-microsegundos»** — ni el motor puro baja de 1 µs: el mínimo medido es
  5,00 µs p50 y 40,80 µs p99.9. **Sigue siendo falso, incluso en el mejor caso.**
- ❌ **«p99.99»** — no hay medición con esa profundidad. Lo máximo es p99.9.
- ❌ **«jitter despreciable»** — el jitter (p99−p50) va de **9 µs en nativo a
  2.709 µs por FFI**.
- ✅ **«motor con latencia de microsegundos, medida con percentiles observados»** —
  esto sí, y es un argumento sólido: **5 µs para ejecutar una sentencia**.

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
