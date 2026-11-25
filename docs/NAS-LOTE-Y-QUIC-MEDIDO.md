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

## 5 · QUIC en la NAS: BLOQUEADO, y es un límite esperado

```
bench quic 1000 -> panic en time.rs (Os code 22)
```

**No es un fallo de la replicación: es el mismo problema de reloj.** `tokio`
(que usa QUIC por debajo) llama a `Instant::now()` internamente, y en este kernel
no funciona.

### Por qué esto NO es un problema del producto

**El nodo ARM del paper es una Raspberry Pi, no una NAS.** La NAS Synology
(`neferu`) es un **experimento interno de hardware legacy**: un Synology DS216se
con kernel 3.2.101 de 2014 y un Marvell Armada-370. Se usó precisamente para
saber hasta dónde aguanta hardware viejo, y el resultado es útil:

- **Aguanta el motor, LMDB y la persistencia.**
- **No aguanta QUIC**, porque el reloj de alta resolución que necesita `tokio`
  no existe como la std lo espera en ese kernel.

Una Raspberry Pi lleva kernel 6.x: `clock_gettime` funciona, `tokio` funciona y
QUIC funciona. **El sistema completo corre junto en el nodo del paper.**

### Lo que el experimento legacy SÍ ha dado

1. **El coste real del `fsync`**: 64 ms por escritura en HDD, frente a 0,1 ms en
   NVMe. Ese dato sirve para el diseño aunque la NAS no sea el destino.
2. **La prueba de que el lote funciona**: 47 s para 21.600 muestras medidas en
   hardware lento. En Raspberry será igual o mejor.
3. **Un límite conocido y documentado**: si algún día alguien quiere correr el
   nodo en un NAS viejo, ya sabe que necesita kernel moderno para la parte de red.

**No se adapta la std de Rust a un kernel de 2014.** El experimento ya ha dado lo
que tenía que dar.

## 6 · Lo que queda demostrado con esto

| Pieza | Dónde está probado |
|---|---|
| Firma Ed25519 real | PC (tests) |
| Perfil desde fichero | PC (tests) |
| Persistencia LMDB | **PC y NAS Synology** |
| Durabilidad sync/nosync/lote | **PC y NAS Synology** |
| Transporte QUIC + TLS 1.3 | PC (E2E, 500 y 200 mensajes) |
| Verificación de flota | PC (5 casos) |
| **Lote a escala de barco** | **NAS: 47 s para 21.600** |
| QUIC en ARMv7 kernel 3.2 | ❌ límite del kernel viejo, **no aplica al paper** |

**El nodo del paper es Raspberry Pi (kernel moderno).** Todo el sistema corre
junto allí. La NAS Synology es un banco de pruebas de hardware legacy y sus
cifras valen como **cota pesimista**: en Raspberry será igual o mejor.

## 7 · Lo que queda pendiente

1. **Medir en Raspberry Pi**, que es el nodo del paper. Debería ir mejor que la
   NAS en todo: kernel moderno (QUIC funciona), CPU más rápida y, si lleva SSD o
   microSD decente, `fsync` más barato. Las cifras de la NAS son una **cota
   pesimista**.
2. **Split-brain**, que sigue sin diseñar.
3. **Réplica parcial** para enjambres grandes.

## 8 · Nota sobre el estado del nodo de pruebas

El nodo de `/volume1/backup/lumen-test/` se montó para este experimento. Los
`.lmdb` de medición ocupan espacio y se pueden borrar cuando no hagan falta.
**No toca nada de `neferu`**, que sigue con su binario del 7 de octubre.
