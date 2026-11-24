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

> ### 🔴 AVISO: las cifras absolutas de esta sección NO son publicables
>
> Todas las mediciones se hicieron en el **portátil de desarrollo (L13)**:
> Intel i7-10510U, CPU al **91 % con otros procesos**, frecuencia bajada a
> **1,73 GHz sobre una base de 2,30 GHz**, y **13,7 de 15,7 GB de RAM** ocupada.
>
> Consecuencia medida: **la misma medición, el mismo código, minutos después,
> dio 1,70 µs donde antes daba 5,00 µs — 3× de diferencia.** Un portátil
> cargado no puede producir una cifra de latencia publicable.
>
> **Para publicar hace falta una máquina dedicada, con el CPU libre y la
> frecuencia fija.** Mientras tanto, esta sección sirve para comparar entre sí
> (motor vs FFI) y para saber el orden de magnitud, **no para citar números**.

Hay **dos bancos** y miden cosas distintas. Confundirlos es el error que hace que
una especificación afirme algo que nadie midió.

### 1. Motor puro (Rust nativo) — `cargo test --release --test bench_nativo`

Mide `Compiler::compile` y `Vm::run` **sin FFI, sin JSON, sin Python**. Es la
cifra del motor.

Órdenes de magnitud observados en el L13 (rango entre pasadas, no un valor):

| Operación | p50 observado | Nota |
|---|---|---|
| compilar 1 línea | **1,7 – 5,0 µs** | varía 3× según carga de la máquina |
| ejecutar 1 asignación | **2,8 – 5,6 µs** | idem |
| `$ORDER` | 4 – 10 µs | idem |
| bucle 100 iteraciones | 170 – 470 µs | idem |

### 2. Viaje completo (Python→FFI→motor) — `bench_latencia.py`

Mide lo que ve un servicio que llama desde Python. Incluye la frontera, que es
**el coste dominante**:

| Operación | p50 observado | Nota |
|---|---|---|
| compilar 1 línea | 14 – 27 µs | rango entre pasadas |
| ejecutar 1 asignación | 92 – 174 µs | idem |
| bucle 100 iteraciones | 380 – 840 µs | idem |

### La comparación que SÍ aguanta

Aunque las cifras absolutas no valgan, **la relación entre ambas columnas sí**,
porque ambas se midieron en la misma sesión y bajo la misma carga:

| | motor nativo | vía Python | factor |
|---|---|---|---|
| compilar 1 línea | ~1,7–5 µs | ~14–27 µs | **~6×** |
| ejecutar 1 asignación | ~2,8–5,6 µs | ~92–174 µs | **~18×** |
| `$ORDER` | ~4–10 µs | ~100–178 µs | **~18×** |

**Conclusión defendible: el cuello de botella es la frontera con Python, no el
motor.** Un servicio escrito en Rust está en la columna izquierda. Eso es una
decisión de arquitectura, y no depende de que el portátil esté ocupado.

**Lo que NO se puede afirmar:**

- ❌ **«sub-microsegundos»** — falso en todo caso. El mínimo observado con la
  máquina libre fue **1,70 µs** y eso es *compilar*, no ejecutar un ciclo. Ni
  en el mejor escenario medido baja de 1 µs.
- ❌ **«5 µs» o cualquier cifra exacta** — depende de la carga. Con el portátil
  libre baja a 1,7; cargado sube a 5.
- ❌ **«p99.99»** — no hay medición con esa profundidad de cola. Lo máximo es p99.9.
- ❌ **«jitter despreciable»** — el jitter medido varía con la carga; en un
  portátil ocupado llega a miles de µs.
- ✅ **«el motor es ~18× más rápido que la frontera FFI»** — esto sí, medido
  consistentemente en sesiones distintas.
- ✅ **«latencia de microsegundos»** — orden de magnitud correcto, sin dar cifra.

### Requisito para publicar una cifra

1. Máquina dedicada, sin otros procesos.
2. CPU a frecuencia fija (`powercfg` en Windows, `performance` governor en Linux).
3. Temperatura estabilizada antes de medir.
4. Repetir 3 pasadas y publicar el **rango**, no la mejor.
5. Decir siempre CPU y frecuencia junto al número.

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
