# DDP de LUMEN — especificación

> **Estado:** implementado y verificado. `implementations/rust/lumen-znet/`
> **Tests:** 31 verdes (`cargo test` en `lumen-znet`)
> **Última revisión:** 2026-11-24

## Por qué existe este documento

Hasta ahora el protocolo DDP de LUMEN se describía como *"deducido del MSM de
Micronetics"*, con los tipos de mensaje marcados como *"nombres plausibles que
inventé"*. Eso era honesto, pero dejaba el protocolo en deuda permanente: nunca
se podía decir si estaba bien o mal, porque dependía de un binario de 1999 que
nadie podía verificar.

**La decisión (24-nov-2026): DDP es de LUMEN.** No buscamos compatibilidad con
Micronetics MSM. Lo que hay aquí es el protocolo, no una aproximación a otro.
La compatibilidad con MSM, si algún día se quiere, será un **adaptador aparte**,
fuera del núcleo.

Consecuencia: los tipos y la cabecera **ya no pueden estar mal**. Son correctos
por definición, y lo que hay que mantener es la coherencia con esta spec.

---

## La cabecera: 6 bytes

```
  byte  0        1    2        3    4        5
       ┌────┬────────────┬────────────┬──────┐
       │tipo│    num1    │    num2    │ flag │
       └────┴────────────┴────────────┴──────┘
         u8      u16 LE       u16 LE      u8
```

| Campo | Bytes | Significado |
|---|---|---|
| `tipo` | 1 | Naturaleza del mensaje. Ver tabla abajo. |
| `num1` | 2 (LE) | Identificador de mensaje. Lo elige el emisor. |
| `num2` | 2 (LE) | Identificador de circuito. Lo asigna `connect()`. |
| `flag` | 1 | Bits de control. `0` = ninguno. |

**Little-endian**, decidido y con test (`los_numeros_de_cabecera_son_little_endian`).

Tras la cabecera va la **carga útil**, sin longitud explícita: el frame LUMEN que
la envuelve ya la delimita. Un mensaje sin carga es válido (0 bytes de cuerpo).

### Por qué 6 bytes y no otra cosa

Es el mínimo que resuelve las cuatro preguntas de un mensaje de agente:
*qué es* (tipo), *cuál* (num1), *por dónde* (num2) y *cómo tratarlo* (flag).
Añadir longitud explícita sería redundante con el framing y costaría 2-4 bytes
por mensaje.

---

## Tipos de mensaje

Estos son los tipos **de LUMEN**, y son definitivos:

| Constante | Valor | Cuándo se usa |
|---|---|---|
| `DATA` | `0x01` | Mensaje con carga útil. El caso normal. |
| `SUCCESS` | `0x02` | Respuesta sin cuerpo: la operación salió bien. |
| `FAILURE` | `0x03` | Respuesta sin cuerpo: la operación falló. |
| `EMPTY` | `0x04` | Respuesta sin cuerpo y sin significado de éxito. |
| `CIRCUIT_ERROR` | `0x0B` | El circuito está roto o no existe. |

`SUCCESS` y `FAILURE` se distinguen **por el tipo**, no por el cuerpo: una
respuesta correcta no necesita llevar bytes para decir que lo es.

---

## El empaquetado base-100 de los identificadores

Los números grandes (identificadores de mensaje de 32 bits) se empaquetan en
**base 100, cuatro bytes**, no como entero binario:

```
valor 42      → [42,  0,   0,  0]
valor 100     → [0,   1,   0,  0]
valor 12345   → [45,  23,  1,  0]
```

La fórmula, que reproduce la de MSM: `[$ZB#100, $ZB@#100, $ZB@00#100, $ZB@0000]`.

**Esto no es un u32 big-endian y confundirlo es un error real** que estuvo en la
primera versión. Para 42 divergen (`[42,0,0,0]` vs `[0,0,0,42]`), y para 12345
divergen por completo. Hay test explícito: `base100_no_es_un_entero_binario`.

Se conserva el esquema base-100 porque **es el que ya hablan los datos
importados del MSM**. Cambiarlo ahora rompería los volúmenes clínicos sin ganar
nada: 4 bytes son 4 bytes.

---

## Cómo viaja sobre LUMEN

Un mensaje DDP se transporta dentro de un **frame LUMEN**:

- El `tipo` del mensaje pasa a ser el **tipo del frame**.
- El `flag` del mensaje se duplica en los **flags del frame**.
- El **payload del frame** son los 5 bytes restantes de cabecera + el cuerpo.

Al recibir se invierte. Un frame cuyo payload no llega a 5 bytes no es un
mensaje DDP y se rechaza (`MalformedMessage`).

Esto permite que DDP viaje sobre cualquier transporte de LUMEN: QUIC, TCP,
stdio o memoria compartida, sin cambiar el protocolo.

---

## Rendimiento medido

Entorno: Lenovo L13 (i7-10510U). Cifras **del codec**, sin red:

| Operación | p50 |
|---|---|
| `encode` mensaje vacío | 200 ns |
| `encode` mensaje 128 B | 200 ns |
| `encode` payload 16 KB | 1,0 µs |
| `decode` payload 16 KB | 1,2 µs |
| **envío por lotes** (1.000 × 134 B) | **204 ns/mensaje → 4,9 M msg/s** |

**El coste es copia de memoria, no la cabecera**: 0,073 ns/byte a 16 KB. Optimizar
la cabecera no daría nada; lo que importa es no copiar de más.

### Optimización aplicada

`flush()` reservaba `vec![0u8; N]` **por cada mensaje**. Medido: 100 ns de coste
por mensaje (100 µs cada 1.000). Ahora el buffer de salida vive en el backend y
solo crece cuando hace falta.

Verificado que la mejora no rompe nada: los 25 tests de `lumen-znet` siguen
verdes después del cambio.

---

## Lo que NO hace

Para que nadie lo asuma:

- **No hay entrega garantizada.** Si el transporte pierde un frame, el mensaje
  se pierde. La fiabilidad es del transporte (QUIC la da, stdio no la necesita).
- **No hay ventana de congestión propia.** Se delega en QUIC.
- **No hay orden garantizado entre circuitos distintos.** Dentro de un circuito,
  sí: `recv_circuit()` los devuelve en el orden en que se encolaron.
- **No hay compatibilidad binaria con Micronetics MSM.** Ver abajo.

## Compatibilidad con MSM: fuera del núcleo

Si algún día hace falta hablar DDP con un MSM real, será:

1. Un **adaptador** que traduzca entre este DDP y el de Micronetics.
2. Fuera de `lumen-znet`, igual que el soporte de cualquier otro protocolo ajeno.

Y antes de escribirlo hay que resolver algo que **hoy no está resuelto**: en el
MSM local DDP está **desactivado por licencia** (`LICENSE.MSM` con `DDP Option:
Off`), así que no existe ni un solo mensaje DDP real capturado contra el que
validar. Sin eso, cualquier adaptador sería otra deducción.

---

## Referencias en código

| Qué | Dónde |
|---|---|
| Cabecera y tipos | `implementations/rust/lumen-znet/src/lib.rs` |
| Conversión DDP ↔ frame | `ddp_to_frame` / `frame_to_ddp` en el mismo fichero |
| Backend de transporte | `src/quic_backend.rs` |
| Benchmark del codec | `tests/bench_ddp.rs` |
| Benchmark de lotes | `tests/bench_lotes.rs` |
| Coste de la asignación | `tests/bench_alloc.rs` |
