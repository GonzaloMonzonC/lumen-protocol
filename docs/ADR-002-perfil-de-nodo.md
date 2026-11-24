# ADR-002 — Perfil de nodo: un binario, varias filas

**Fecha:** 24-nov-2026
**Estado:** aceptado (decisión de Gonzalo)
**Contexto:** paper P2P + auditoría del repo (`lumen-znet/tests/quic_e2e.rs`, `host.rs:1440`, `quic.rs:115`)

---

## Decisión

Existe **un solo producto de nodo** (`lumen-nodo`). PC, NAS y barco son **el mismo
binario** con distinta fila de configuración. El **navegador es otro producto**
y no entra en esta tabla.

## Por qué el navegador queda fuera

No es una valoración: es una incapacidad medida.

| lo que el nodo necesita | nativo | navegador |
|---|---|---|
| socket UDP | `UdpSocket::bind` | no existe |
| QUIC con TLS 1.3 | `quinn` + `rustls` | hay que usar WebTransport (otra API) |
| disco propio | `std::fs` + sqlite | OPFS, no implementado |
| reloj estable | `Instant::now` | aproximado, la pestaña duerme |
| seguir vivo | es un proceso | lo mata el usuario |
| compilar a wasm | — | **hoy falla** (`getrandom`) |

Además `host.rs:2832` devuelve error a propósito en `web:fetch` dentro de WASM:
por diseño, el navegador no es un par de red. Comparte **el frame** y **el trait
`Host`**; no comparte ciclo de vida.

---

## El perfil (la tabla)

La tabla vive en la PDB, bajo `^SYS("NET",...)`. **Solo puede contener valores
cuyo código existe y tiene test.** Un valor sin implementación no es un valor:
es una mentira con forma de bandera.

```m
^SYS("NET","mode")         = "lan" | "wan" | "offline"
^SYS("NET","role")         = "hub" | "store" | "edge"
^SYS("NET","discovery")    = "multicast" | "none" | "seeds"*
^SYS("NET","transport")    = "quic" | "shm"
^SYS("NET","identity")     = "pin" | "none" | "pubkey"*
^SYS("NET","storage")      = "lmdb" | "sqlite"
^SYS("NET","pin")          = "<sha256 hex del certificado del par>" (requerido si identity=pin)
^SYS("NET","sign")         = "none" | "hash-chain"
^SYS("NET","auth")         = "macaroon" | "hmac" | "dev"
```

`*` = **no implementado**. El binario arranca y lo dice en la cara, no en un log.

### Estado real de cada valor (medido, no supuesto)

| valor | código | prueba |
|---|---|---|
| `mode=lan` | sí | `quic_e2e` en LAN/localhost |
| `mode=offline` | sí | no abre endpoint (trivial) |
| `mode=wan` | **parcial** | QUIC funciona; NAT no (no hay ICE/STUN) |
| `role=hub` | sí | acepta y escribe en PDB |
| `role=store` | sí | idem + sirve `pull` |
| `role=edge` | sí | conecta hacia afuera |
| `discovery=multicast` | **no** | `datagram.rs:165` tiene `join_multicast`, nadie lo usa |
| `discovery=none` | sí | requiere peer explícito |
| `transport=quic` | **sí** | `lumen-znet/tests/quic_e2e.rs:20` verde |
| `transport=shm` | sí | `shm.rs` |
| **`identity=pin`** | **sí** | `PinnedVerifier` + `pinned_client_config` en `quic.rs`; `lumen-znet/tests/pin_e2e.rs` verde (2/2) |
| `identity=none` | sí | `SkipCertVerifier` — solo dev |
| `identity=pubkey` | **no** | por hacer |
| `sign=none` | sí | — |
| `sign=hash-chain` | **sí** | `cadena.rs` + `tests/cadena_lmdb.rs` (borra la muestra 5 de 8 y la localiza, incluso tras reabrir el LMDB) |
| `auth=macaroon` | sí (Python) | `tests_macaroon.py` 31/31 |
| `auth=hmac` | sí | DDP firmado, verificado hoy |
| `auth=dev` | sí | **y debe negarse a escuchar fuera de 127.0.0.1** |

### `storage` — el motor es configuración, no build

`sqlite` carga la base en RAM al abrir; `lmdb` lee por mmap sin precarga, que es
lo que permite a un nodo con la PDB grande arrancar en segundos. Elegirlo es una
fila del perfil, no un recompilado distinto.

| valor | motor | verificado |
|---|---|---|
| `storage=lmdb` | `MemoryHost::from_lmdb` (mmap, directorio) | escribe, **persiste tras cerrar y reabrir**, y ve la **misma clave** que sqlite (`lmdb_y_sqlite_ven_la_misma_clave`) |
| `storage=sqlite` | `MemoryHost::from_sqlite` (fichero) | escribe y persiste tras reabrir |

Si se pide `storage=lmdb` en un binario compilado sin la feature `motor-lmdb`,
`validate()` devuelve `NotImplemented` y **el nodo no arranca**: arrancar
leyendo con sqlite mientras la config dice lmdb sería exactamente la mentira que
este ADR prohíbe.

⚠️ Confusión clásica: **sqlite trabaja sobre un fichero, LMDB sobre un
DIRECTORIO** (`data.mdb` + `lock.mdb`). El binario imprime cuál usa y de dónde
sale antes de servir.

---

## Bug de transporte encontrado al conectar dos nodos (24-nov-2026)

El primer día que dos `lumen-nodo` hablaron de verdad, el receptor procesó
**frames válidos de longitud 0** después de cada frame bueno: 6 frames
"aplicados" y 8.223 bytes cuando se habían enviado 31.

No era el nodo: era `QuicTransport::read`. `read_buffer` se redimensiona a
65.536 con ceros y `recv.read` solo llena los primeros `n`; la condición de
"quedan pendientes" comparaba contra el **tamaño del Vec** (65.536) en lugar de
contra los bytes leídos. Resultado: tras la primera lectura real, la siguiente
entregaba ~65 KB de relleno y **perdía** los bytes de la segunda lectura.

Arreglado con un campo `read_len` (bytes reales) y regresión en
`lumen-znet/tests/read_sin_relleno.rs`. Afectaba a **cualquier** consumidor del
transporte (nodo, znet, MCP), no solo al nodo. Commit `98083504`.

**Lección para el ADR:** este fallo no se veía leyendo el código ni con tests
unitarios del codec. Salió al ejecutar dos procesos. Es el argumento más fuerte
para que el ADR exija *código con test ejecutado*, y no solo código.

### `identity=pin` — qué hace exactamente

El cliente QUIC compara la huella SHA-256 del certificado que presenta el par
con la fijada en `^SYS("NET","pin")`. Si no coincide, **el handshake no se
completa** — no hay conexión, no hay "aviso y sigo".

No es PKI: no hay autoridad ni cadena de confianza. Es "confío exactamente en
este nodo y en ningún otro", que es lo que un PC↔NAS necesita antes de que
exista una raíz de flota. La huella se obtiene del propio nodo servidor
(`server_with_pin()` la devuelve al arrancar).

**Verificado** (`lumen-znet/tests/pin_e2e.rs`): con la huella correcta el frame
DDP viaja y vuelve intacto; con la huella de otro nodo, el handshake falla.

---

## Regla de la seguridad sobre la configuración

**Un `mode=lan` con `auth=dev` no puede escuchar en `0.0.0.0`.** Sin excepción.
Un modo de desarrollo que acepta conexiones de la red no es un modo de
desarrollo: es una puerta abierta con una etiqueta que dice "dev".

El binario valida su perfil al arrancar y **se niega a arrancar** si el perfil
es incoherente. No avisa y sigue: no arranca.

---

## Perfiles de referencia

| | PC (L13) | NAS (Neferu) | Barco |
|---|---|---|---|
| `mode` | `lan` | `lan` | `wan` |
| `role` | `hub` | `store` | `edge` |
| `discovery` | `multicast`* | `multicast`* | `seeds`* |
| `transport` | `quic` | `quic` | `quic` |
| `identity` | `pin` | `pin` | `pubkey`* |
| `sign` | `none` | `none` | `hash-chain` |
| `auth` | `hmac` | `hmac` | `macaroon` |

Los `*` marcan lo que hay que escribir. **Hoy arrancan: `identity=none` (dev),
`identity=pin` y `sign=hash-chain`.** Al perfil del barco solo le falta
`pubkey`.

---

## `sign=hash-chain` — integridad, no autoría

El valor se guarda encadenado, en texto plano legible desde M:

```
<valor>|<prev_hash>|<hash>          hash = sha256(prev || valor)
```

Cada 100 muestras se sella el bloque (`sha256(sello_anterior || hashes...)`),
lo que permite verificar 21.600 muestras con 216 comprobaciones en vez de
21.600 — la diferencia entre verificar a bordo o no poder.

**⚠️ Lo que la cadena prueba y lo que no:**

| prueba | no prueba |
|---|---|
| que no falta ningún tramo (y cuál falta) | **quién** escribió las muestras |
| que nadie alteró una muestra sin romper la cadena | que el emisor sea quien dice ser |
| que el orden es el correcto | que el dato sea verdadero |

Para autoría hace falta `identity=pin` (hoy) o `pubkey` (pendiente). Decir
"firmado" cuando solo hay cadena es exactamente el tipo de exageración que este
ADR existe para evitar.

**Reescribir el pasado se rechaza:** encadenar una muestra anterior a la última
de su serie rompería todo lo que cuelga de ella, así que el nodo lo niega.

**El estado vive en `^CADENA` y no se acepta por red.** Si un par pudiera
escribir el "último hash", falsearía el pasado de una serie entera. Es una
caché, no la verdad: si se pierde, se reconstruye recorriendo la serie con
`--verificar`.

---

## Consecuencias

**A favor:** un bug se arregla en los tres sitios a la vez. La cadena de hashes
se activa en los barcos con una fila, no con un fork.

**En contra:** un perfil mentiroso arruina la ventaja. De ahí la regla de
"ningún valor sin código y test", que es la única cosa que impide que esta
tabla se convierta en el paper otra vez.
