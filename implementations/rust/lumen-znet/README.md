# `lumen-znet` — `$ZNET` de MSM sobre LUMEN

**Crate de reimplementación de la primitiva de red de MSM**

---

## Qué es

`$ZNET` no es una rutina: es una **función intrínseca del intérprete MSM**, como `$V` o `$ZAS`.
No se puede extraer de la base de datos. Hay que reimplementarla.

Este crate la reimplementa **sobre frames LUMEN** en vez de sobre la pila de red nativa.

## Por qué

En las 438 rutinas extraídas de `DATABASE.MSM`, `$ZNET` aparece en **solo 3 ficheros**:

| Rutina | Usos | KB |
|---|---|---|
| `DDPSRV` | 6 | 0,6 |
| `STUDDP` | 1 | 2,4 |
| `WSAGENT` | 2 | 0,9 |

**3 de 438 rutinas, 3,9 KB.** Ese es todo el código que toca la red en un sistema de replicación
de 30 años.

Y usa solo seis funciones: `(8)`, `(9,x)`, `(17)`, `(22,M)`, `(30)`, `(31)`.

## Las seis funciones

| `$ZNET` | Semántica | API del crate |
|---|---|---|
| `(17)` | inicializar red | `Znet::init()` |
| `(22, M)` | crear circuito | `Znet::connect(dest)` |
| `(30)` | inicializar enlace | `Znet::link_init(dest)` |
| `(8)` | recv bloqueante | `Znet::recv()` |
| `(9, x)` | responder | `Znet::reply(circuit, reply)` |
| `(31)` | recv de circuitos | `Znet::recv_circuit()` |

### `$ZNET(9, x)` — las cuatro respuestas de `DDPSRV`

| Llamada | Significado | `ZnetReply` |
|---|---|---|
| `$ZNET(9, "S")` | success | `Success` |
| `$ZNET(9, "F")` | failure | `Failure` |
| `$ZNET(9, "")` | vacío | `Empty` |
| `$ZNET(9, $ZCHAR(...))` | datos binarios | `Data(Vec<u8>)` |

Los 4 bytes big-endian que `DDPSRV` construye con `$ZCHAR($ZB##100, $ZB\#100##100,
$ZB\#10000##100, $ZB\#1000000)` viajan intactos en `Data`.

## El mapeo de mensajes

DDP transporta mensajes con cabecera de posiciones fijas:

```
M: [tipo:1][num1:2 LE][num2:2 LE][flag:1][carga útil...]
   └────────────── 6 bytes ──────────────┘
```

LUMEN frames son `[Hyb128 len][type:1][flags:1][payload]`.

**El tipo de mensaje DDP pasa a ser el tipo del frame LUMEN.** Eso permite clasificar sin
deserializar el cuerpo — que es justo para lo que LUMEN diseñó el campo `type`.

```
M[1]     tipo     →  frame type
M[2..3]  num1     →  payload[0..2]   (id de mensaje)
M[4..5]  num2     →  payload[2..4]   (circuito)
M[6]     flag     →  frame flags
M[7..]   carga    →  payload[5..]
```

El resultado: un mensaje DDP de solo cabecera (un ACK) ocupa **8 bytes** en LUMEN en vez de 6 en
crudo — pero a cambio gana Hyb128, diccionario y capacidad de multiplexación.

## Qué está probado

**22 tests, todos pasan.**

### Unitarios (10) — el mapeo es reversible

- `init` es obligatorio para conectar
- circuito repetido devuelve el mismo id
- destino vacío falla como en `WSAGENT` (`FAILCODE=51`)
- mensaje DDP ida y vuelta
- mensaje corto se rechaza con `MalformedMessage`
- DDP → LUMEN → DDP conserva todos los campos
- `recv` y `reply` usan colas distintas
- `Failure` y `Empty` tienen tipos distintos
- `reply` con datos binarios conserva los bytes
- cerrar circuito lo quita

### Integración (4) — contra el codec REAL de LUMEN

Estos son los que importan. No usan mi codec contra sí mismo: usan `lumen::frame::build` y
`lumen::frame::parse`, el codec de verdad.

- **`un_mensaje_ddp_cabe_en_un_frame_lumen_valido`** — construye con `frame::build`, parsea con
  `frame::parse`, y comprueba que `consumed == written` y que el mensaje DDP vuelve intacto
- **`el_overhead_de_lumen_es_menor_que_el_de_ddp_crudo`** — un ACK ocupa 8 bytes exactos
- **`un_frame_lumen_ajeno_no_se_confunde_con_ddp`** — un payload corto se rechaza
- **`muchos_mensajes_seguidos_se_parsean_uno_a_uno`** — 50 mensajes en un stream, leídos frame a
  frame usando `consumed`. Es el bucle de `DDPSRV`: recv, actuar, responder, repetir

### E2E sobre QUIC real (2)

- **`un_mensaje_ddp_viaja_por_quic_de_verdad`** — servidor y cliente QUIC de verdad, mensaje DDP
  de ida y ACK de vuelta, campos comprobados en ambos extremos
- **`el_backend_generico_funciona_sobre_un_vec`** — el backend funciona sobre cualquier
  `Transport`

```
running 16 tests ... test result: ok. 16 passed; 0 failed
running 4 tests  ... test result: ok. 4 passed; 0 failed
running 2 tests  ... test result: ok. 2 passed; 0 failed
```

**Y los 176 tests de `lumen` siguen pasando** tras corregir `quic.rs`.

## Transporte QUIC

`src/quic_backend.rs` conecta la cola en memoria con un stream real. `QuicZnet<S: Transport>`:

| Método | Qué hace |
|---|---|
| `flush()` | saca los replies de la cola de circuitos y los escribe como frames LUMEN |
| `poll()` | lee del stream, parte en frames con `frame::parse` usando `consumed` |
| `pump()` | las dos cosas: el cuerpo del bucle de `DDPSRV` |

Usa el trait `lumen::transport::Transport`, no `std::io::Read + Write`: sirve sobre QUIC, TCP o
stdio sin cambiar nada, y se puede probar con un buffer en memoria.

**Verificado sobre QUIC real** — servidor y cliente, handshake TLS, ida y vuelta:

```text
[srv] frame DDP recibido: num1=300 num2=7 body="^SYS(\"JOURNAL\",1)=p1^p2"
[srv] ACK enviado (8 bytes)
```

`num1=300` es `0x012C` intacto, y la carga útil llega sin tocar.
### Dos bugs encontrados en `QuicTransport` de LUMEN

Al escribir el E2E aparecieron dos fallos en `src/quic.rs`, **no en este crate**:

1. **`read` bloqueaba hasta EOF.** Usaba `recv.read_to_end(65536)`, que espera a que el par cierre
   el stream. Inutilizable para petición/respuesta: el receptor no ve bytes hasta que el emisor
   termina, y el emisor no termina porque espera respuesta. Deadlock. Síntoma: 30 s exactos de
   espera y el servidor aceptaba sin leer nunca.
2. **El buffer de lectura tenía capacidad 0.** `Vec::new()` pasado como slice a `recv.read`
   devuelve 0 bytes, indistinguible de un cierre limpio. El cliente leía 0 y creía que el stream
   estaba cerrado.

Los dos pasaban desapercibidos porque los tests existentes de `quic.rs` usan los streams de quinn
directamente, no el trait `Transport`. Ambos corregidos.

## Qué NO está hecho

- ❌ **No está probado contra el MSM original.** El formato de mensaje se dedujo de la rama 12 de
  `DDPSRV`, que **está comentada en el original**. Los 22 tests construyen los mensajes con este
  mismo código: prueban coherencia interna, **no compatibilidad con el MSM**.
- ❌ **No está probado contra el MSM original.** El formato se dedujo leyendo `DDPSRV`, `STUDDP` y
  `WSAGENT` extraídos de `DATABASE.MSM`. La deducción es coherente con el uso, pero **no hay
  documentación oficial de `$ZNET` en la máquina**.
- ❌ **No es un plugin de YottaDB.** Es un crate Rust. Para llamarlo desde MUMPS haría falta el
  puente de call-out (ver `ZNET-Y-TRANSPORTE.md`), que **YottaDB descartó** por la decisión de
  mantener MSM vivo.
- ❌ No se ha probado en i686 ni en los nodos de 2010.

## Cómo se usa

```rust
use lumen_znet::{Znet, DdpMessage, msg_type, ddp_to_frame};

let mut z = Znet::new();
z.init();                                   // $ZNET(17)
let circuit = z.connect("192.168.1.10")?;   // $ZNET(22, M)

// Llega un mensaje de la red
z.push_incoming(DdpMessage::new(msg_type::DATA, 1, circuit, 0, b"payload".to_vec()));

// Bucle de DDPSRV
while let Some(msg) = z.recv() {            // $ZNET(8)
    // ... procesar ...
    z.reply(circuit, ZnetReply::Success)?;  // $ZNET(9, "S")
}
```

## Estado

| Aspecto | Estado |
|---|---|
| Codec DDP ↔ LUMEN | ✅ hecho, 14 tests |
| Las 6 funciones | ✅ hechas |
| Compatibilidad con codec LUMEN real | ✅ verificada por tests de integración |
| Transporte de red | ✅ QUIC, verificado E2E |
| Validación del certificado del par | ❌ expuesto pero no validado |
| Probado contra MSM original | ❌ no |
| Auditoría de seguridad | ✅ `cargo audit` → 0 |
