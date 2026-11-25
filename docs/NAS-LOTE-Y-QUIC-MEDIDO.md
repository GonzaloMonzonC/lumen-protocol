# Lote y QUIC medidos en la NAS

> 2026-11-24. Medición real en la NAS (ARMv7, HDD rotacional, kernel 3.2.101).
> Binario `bench_lote` con **reloj externo**.

---

## 1 · Por qué el reloj va fuera del binario

La NAS hace **panic en `Instant::now()` y en `SystemTime::now()`**:

```
called `Result::unwrap()` on an `Err` value:
  Os { code: 22, kind: InvalidInput, message: "Invalid argument" }
```

Kernel **3.2.101 (2014)** sobre Marvell Armada-370. El reloj de alta resolución
no está disponible como lo espera la std de Rust.

**Solución**: el binario solo hace el trabajo y cuenta commits; el tiempo lo
toma el shell (`date +%s%N`) alrededor. Menos elegante, pero fiable.

## 2 · El lote, medido (500 hechos)

| k (commit cada) | Commits | Tiempo | ms/hecho |
|---|---:|---:|---:|
| **1** (`sync`) | 500 | **32.106 ms** | 64,2 |
| 8 | 63 | 4.595 ms | 9,2 |
| **64** | 8 | **839 ms** | **1,7** |
| 256 | 2 | 284 ms | 0,57 |

**`lote` 64 es 38× más rápido que `sync`**, y todavía conserva fsync 1 de cada 64
escrituras. Es el punto medio real, no una estimación.

## 3 · El caso del paper: 21.600 muestras (6 h de barco a 1 Hz)

| Modo | Tiempo | Pérdida ante corte |
|---|---:|---|
| `sync` | ~23 min (extrapolado) | nada |
| **`lote` 64** | **46,9 s** | ≤ 64 muestras |
| **`lote` 256** | **11,2 s** | ≤ 256 muestras |
| `nosync` | 4,1 s | lo último en vuelo |

**El perfil de barco con `lote` 64 sincroniza 6 horas de bitácora en 47 segundos
y no pierde más de un minuto de telemetría ante un corte.** Ese es el equilibrio
que buscábamos, y ahora está medido, no calculado.

## 4 · Validación del perfil

El perfil de barco usa `lote` 64. La medición dice que:

- Con `sync` (lo que había antes de configurarlo) serían **23 minutos** por barco.
- Con `lote` 64 son **47 segundos**.
- Bajar a 256 ahorra 35 s más pero multiplica por 4 la ventana de pérdida.

**64 es una decisión razonable y ahora tiene respaldo numérico.**

## 5 · QUIC en la NAS: BLOQUEADO

```
bench quic 1000 -> panic en time.rs (Os code 22)
```

**No es un fallo de la replicación: es el mismo problema de reloj.** `tokio`
(que usa QUIC por debajo) llama a `Instant::now()` internamente, y en este kernel
no funciona.

### Opciones

1. **Probar QUIC en el PC** y en la NAS solo el almacenamiento. Es lo que ya
   está hecho: `quic_e2e` y `flota_multinodo` corren en el PC (174 tests).
2. **Ver si el kernel de la NAS puede usar otro reloj.** Requiere arrancar el
   proceso con otra `LD_PRELOAD` o tocar el kernel: no viable en un Synology.
3. **Buscar un backoff de tokio** hacia `clock_gettime` con otra base de tiempo:
   `tokio` no lo expone.
4. **Aceptar el límite.** La NAS es un nodo de almacenamiento; la replicación se
   probaría en otro nodo (Raspberry, x86, el propio PC).

**Mi lectura: la opción 4 es la realista.** Este kernel tiene 11 años y no es
razonable adaptar la std de Rust a él. La NAS sirve perfectamente como nodo de
datos y almacenamiento; la replicación está probada en hardware moderno.

## 6 · Lo que queda demostrado con esto

| Pieza | Dónde está probado |
|---|---|
| Firma Ed25519 real | PC (tests) |
| Perfil desde fichero | PC (tests) |
| Persistencia LMDB | **PC y NAS** |
| Durabilidad sync/nosync/lote | **PC y NAS** |
| Transporte QUIC + TLS 1.3 | PC (E2E, 500 y 200 mensajes) |
| Verificación de flota | PC (5 casos) |
| **Lote a escala de barco** | **NAS: 47 s para 21.600** |
| QUIC en ARMv7 kernel 3.2 | ❌ **bloqueado por el reloj** |

## 7 · Lo que queda pendiente

1. **Decidir si el nodo ARM del paper es tipo NAS (kernel viejo) o tipo
   Raspberry (kernel moderno).** Si es Raspberry, QUIC funcionará y todo el
   sistema corre junto. Si es NAS, son dos piezas separadas.
2. **Probar QUIC en otro ARM** (Raspberry) para saber si el límite es del kernel
   3.2 o de ARM en general.
3. **Split-brain**, que sigue sin diseñar.
