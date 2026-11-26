# Estado real por afirmación — LUMEN

> Documento vivo. Cada fila es una afirmación que **aparece en material público
> o en los documentos de especificación**, con su estado comprobado contra el
> repo. La regla: si algo está en la columna «NO IMPLEMENTADO», no se puede
> presentar como característica del producto.

**Última verificación:** 24-nov-2026 (replicación de hechos añadida el 26-nov-2026) · repo `lumen-protocol` · 120 ficheros `.rs`
escaneados + tests ejecutados.

## Cómo leer esta tabla

| Estado | Significa |
|---|---|
| ✅ **VERIFICADO** | Implementado y con test o medición que lo respalda |
| 🟡 **PARCIAL** | Existe, pero con límites que hay que decir al contarlo |
| 🔵 **DISEÑO** | Documentado, no implementado. Se puede presentar como hoja de ruta |
| ❌ **NO EXISTE** | Afirmado en algún sitio y no hay código. **No usar en material público** |

---

---

## Replicación de hechos firmados (el DDP de los papers)

> **Ojo con la homonimia.** Hay dos cosas llamadas DDP en el repo:
>
> - **DDP de estado** (`ddp.rs`, `pdb-sync`): sincroniza claves de la PDB entre
>   nodos. Existe desde antes y tiene sus propios límites (solo propaga claves
>   nuevas, no cambios ni borrados).
> - **DDP de hechos** (`lumen-nodo`): replicación de un registro append-only de
>   hechos firmados. **Es el que soporta los escenarios de los papers** (flota,
>   criptomoneda, enjambre) y el que se ha construido y medido estos días.
>
> Las filas de esta tabla son del **DDP de hechos**.

| Afirmación | Estado | Evidencia |
|---|---|---|
| Hechos inmutables con identidad `(nodo, serie, seq, instancia)` | ✅ VERIFICADO | `replicacion.rs`; el nodo va dentro para que dos barcos no colisionen |
| Firma Ed25519 real del hecho | ✅ VERIFICADO | `identidad.rs`; tests de firma, manipulación e impostor |
| Cadena de hashes por serie | ✅ VERIFICADO | `cadena::hash_muestra`; verifica sin huecos |
| Sello de bloque cada 100 (la firma cubre los 100 hashes) | ✅ VERIFICADO | `firmar_bloque` + `verificar_solo_bloques`. **Se descubrió que firmar solo la muestra 99 dejaba un agujero** |
| Formato v2 con versión (v1 y v2 conviven) | ✅ VERIFICADO | `contenido_canonico` elige payload según versión; los hechos v1 **no se re-firman** |
| Persistencia en LMDB que sobrevive al reinicio | ✅ VERIFICADO | `hechos_lmdb.rs`; 200 hechos + firmas sobreviven y la manipulación en disco se detecta |
| Replicación por QUIC + TLS 1.3 con pin de huella | ✅ VERIFICADO | `quic_e2e.rs` (200 mensajes), `flota_multinodo.rs` |
| Servidor QUIC que acepta conexiones en paralelo | ✅ VERIFICADO | `aceptar_conexion()`; 10 → 40 barcos |
| Idempotencia (reenviar no duplica) | ✅ VERIFICADO | `recibir_hechos` cuenta duplicados por hash |
| **Split-brain: dos ramas coexisten y el conflicto se registra** | ✅ VERIFICADO | `split_brain.rs`: 6 hechos, 6 guardados, 3 conflictos. **Antes se perdían 3 en silencio** |
| **Custodia de epoch** (un salto exige firma del anterior) | ✅ VERIFICADO | `epoch.rs` + `recibir_hechos_custodiados`; epoch 999 sin cadena se rechaza |
| **Verificación de flota en la recepción** | ✅ VERIFICADO | `recibir_hechos_de_flota`; sin certificado de la raíz del armador no entra nada |
| Un barco no puede firmar hechos a nombre de otro | ✅ VERIFICADO | `flota_recepcion.rs`; certificado de A + hechos de B = rechazo |
| Perfiles de replicación configurables (JSON) | ✅ VERIFICADO | 4 perfiles: barco, enjambre, ledger, config; retención, firma, durabilidad, conflicto, mapsize |
| Durabilidad configurable: `sync` / `nosync` / `lote` | ✅ VERIFICADO | Medido en NAS: 64 ms/escritura con fsync, 0,41 ms sin él |
| Crecimiento automático del mapa de LMDB | ✅ VERIFICADO | `crecer_mapa`; arrancó en 32 MB, creció a 128, guardó 240.000 hechos |
| `poll`/`pump` con estado explícito (`Vacio` vs `Cerrado`) | ✅ VERIFICADO | `Lectura`; cierra la ambigüedad del `0` |
| Medida en hardware real (NAS ARMv7) | ✅ VERIFICADO | 21.600 muestras: 4,1 s con nosync · 47 s con lote 64 · 23 min con fsync |
| Medida de flota | ✅ VERIFICADO | 40 barcos → 480.000 hechos, cero pérdidas |
| **Consenso (PoW/PoS/BFT)** | ❌ **NO EXISTE** | Por diseño: el paper no lo pide. La custodia de epoch es una cadena de firmas verificable, no consenso |
| **Revocación de certificados** | ❌ **NO EXISTE** | Si un barco se compromete no hay forma de retirarle el certificado sin cambiar la raíz |
| **Caducidad de certificados** | ❌ **NO EXISTE** | Un certificado de hace 5 años sigue valiendo |
| **Epoch de recuperación si se pierde la clave** | 🔵 DISEÑO | El barco queda atrapado en su epoch. Haría falta firma de la raíz del armador, que hoy firma certificados y no recuperaciones |
| **Réplica parcial (enjambres grandes)** | 🔵 DISEÑO | La política `interes` existe en el perfil, sin probar a escala |
| **El hub de simulación usa `recibir_hechos_de_flota`** | 🟡 PARCIAL | La función está probada; `sim_flota` aún no emite certificados |

### Lo que se midió y hay que decir

| Número | Dónde | Documento |
|---|---|---|
| 480.000 hechos, 40 barcos, 0 pérdidas | PC | `FLOTA-REPLICANDO.md` |
| 21.600 muestras en 4,1 s (`nosync`) | NAS ARMv7 | `NAS-LOTE-Y-QUIC-MEDIDO.md` |
| Lote 64 = 47 s · fsync = 23 min | NAS ARMv7 | idem |
| Verificar Ed25519: 78 µs PC / 3.555 µs NAS | ambos | `COSTE-VERIFICACION-NAS-VS-PC.md` |
| La cadena cuesta 2,4× las firmas en PC; en ARM las firmas dominan 43× | ambos | idem |
| El hub aguanta 40 barcos (antes 10) | PC | `QUIC-SERVIDOR-PARALELO.md` |


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

> ### 🔴 AVISO: las cifras absolutas son de un portátil de desarrollo
>
> Todas las mediciones se hicieron en el **Lenovo L13**: Intel i7-10510U
> (4 núcleos / 8 hilos, 1,80 GHz base, 2,30 GHz sostenido), **15,7 GB de RAM
> con 13,3 GB ocupados** por el entorno de desarrollo.
>
> **Lo que está medido de verdad son 5 pasadas con la carga registrada**, y la
> correlación es directa (tabla abajo). Lo que se extrapole a otra máquina es
> **estimación**, no medición, y así está marcado.

### 1. Motor puro (Rust nativo) — `bench_nativo.rs`

`Compiler::compile` y `Vm::run`, **sin FFI, sin JSON, sin Python**. 20.000
iteraciones por caso, 5 pasadas, midiendo la CPU antes y después de cada una:

| caso | compilar p50 (min/med/max) | ejecutar p50 (min/med/max) |
|---|---|---|
| 1 línea | 2,0 / **3,6** / 4,9 µs | — |
| 4 líneas | 4,6 / 8,3 / 11,1 µs | 7,8 / 8,6 / 17,1 µs |
| aritmética | 2,2 / **2,3** / 5,0 µs | 4,6 / 7,2 / 8,9 µs |
| asignación | — | 3,4 / **4,6** / 7,6 µs |
| `$ORDER` | 2,6 / 3,1 / 5,6 µs | 6,0 / **7,0** / 11,4 µs |
| bucle 100 iter | 3,5 / 4,9 / 8,4 µs | 203 / **268** / 469 µs |

**La correlación con la carga es la prueba de que esto no es ruido inventado:**

| pasada | CPU antes → después | compilar 1 línea |
|---|---|---|
| 5 | 13,6 % → 18,8 % | **2,0 µs** |
| 1 | 19,5 % → 82,0 % | 2,3 µs |
| 3 | 60,9 % → 81,1 % | 3,6 µs |
| 2 | 95,7 % → 52,7 % | **4,9 µs** |

A más carga, más latencia. Con la máquina libre, **2,0 µs**.

### 2. Extrapolación a otra máquina — ESTIMACIÓN, no medición

Factores de rendimiento **monohilo** (lo que importa: una fibra ejecutando M):

| máquina | factor | ejecutar 1 asignación | bucle 100 iter |
|---|---|---|---|
| **L13 medido** (CPU libre) | 1,15 | 2,4 – 4,9 µs | 148 – 409 µs |
| Apple M1 | 1,70 | **1,6 – 3,3 µs** | 100 – 277 µs |
| Ryzen 7 5800X | 1,75 | **1,6 – 3,2 µs** | 97 – 269 µs |
| Apple M2 Pro | 2,00 | **1,4 – 2,8 µs** | 85 – 235 µs |
| Xeon Silver 4314 | 1,30 | 2,2 – 4,3 µs | 131 – 362 µs |
| EPYC 7763 | 1,35 | 2,1 – 4,1 µs | 126 – 348 µs |
| Raspberry Pi 4 (contraste) | 0,35 | 8,0 – 16,0 µs | 486 – 1.343 µs |
| NAS ARMv7 neferu (contraste) | 0,12 | 23,3 – 46,7 µs | 1.417 – 3.917 µs |

**Tres avisos que van con esta tabla, sin los cuales es marketing:**

1. El factor es **monohilo**. Un EPYC de 128 hilos no hace una fibra más rápida:
   escala en fibras concurrentes, no en latencia individual.
2. Esto mueve bytes en caché y memoria. **Fuera de caché domina la latencia de
   RAM**, y el factor real será peor que el de CPU.
3. **Solo el L13 está medido.** Todo lo demás es estimación a partir de factores
   públicos. Para publicar una cifra de otra máquina hay que medir en ella.

### 3. Viaje completo (Python→FFI→motor) — `bench_latencia.py`

| Operación | p50 observado |
|---|---|
| compilar 1 línea | 14 – 27 µs |
| ejecutar 1 asignación | 92 – 174 µs |
| bucle 100 iteraciones | 380 – 840 µs |

### La comparación que SÍ aguanta

Medida en la misma sesión y bajo la misma carga, así que la **relación** sobrevive
aunque las cifras absolutas no:

| | motor nativo | vía Python | factor |
|---|---|---|---|
| compilar 1 línea | ~2–5 µs | ~14–27 µs | **~6×** |
| ejecutar 1 asignación | ~3–6 µs | ~92–174 µs | **~18×** |
| `$ORDER` | ~6–11 µs | ~100–178 µs | **~18×** |

**Conclusión de arquitectura: el cuello de botella es la frontera con Python,
no el motor.** Un servicio en Rust está en la columna izquierda. Eso no depende
de que el portátil esté ocupado.

**Lo que NO se puede afirmar:**

- ❌ **«sub-microsegundos»** — falso en todo caso. El mínimo observado con la
  máquina libre fue **2,0 µs compilando**, y el mínimo extrapolado a un M2 Pro
  es 1,4 µs. **Ningún escenario medido o estimado baja de 1 µs.**
- ❌ **«5 µs» o cualquier cifra exacta del L13** — depende de la carga: 2,0 µs
  libre, 4,9 µs al 95 %.
- ❌ **«p99.99»** — no hay medición con esa profundidad. Lo máximo es p99.9.
- ✅ **«ejecuta una sentencia M en 3–5 µs»** (L13, mediana de 5 pasadas).
- ✅ **«~2 µs en hardware moderno»** (estimación con factor monohilo, no medición).
- ✅ **«el motor es ~18× más rápido que la frontera FFI»** — medido.

### Requisito para publicar una cifra

1. Máquina dedicada, sin otros procesos.
2. CPU a frecuencia fija (`powercfg` en Windows, `performance` governor en Linux).
3. Temperatura estabilizada antes de medir.
4. Repetir **3–5 pasadas** y publicar el **rango**, no la mejor.
5. Decir siempre CPU, frecuencia y memoria libre junto al número.

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
