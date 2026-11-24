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
^SYS("NET","pin")          = "<sha256 hex del certificado del par>" (requerido si identity=pin)
^SYS("NET","sign")         = "none" | "hash-chain"*
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
| `sign=hash-chain` | **no** | por hacer (barcos) |
| `auth=macaroon` | sí (Python) | `tests_macaroon.py` 31/31 |
| `auth=hmac` | sí | DDP firmado, verificado hoy |
| `auth=dev` | sí | **y debe negarse a escuchar fuera de 127.0.0.1** |

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
| `sign` | `none` | `none` | `hash-chain`* |
| `auth` | `hmac` | `hmac` | `macaroon` |

Los `*` marcan lo que hay que escribir. **Hoy arrancan: `identity=none` (dev) e
`identity=pin` (con la huella del par). El perfil del barco espera `pubkey` y
`hash-chain`.**

---

## Consecuencias

**A favor:** un bug se arregla en los tres sitios a la vez. La cadena de hashes
se activa en los barcos con una fila, no con un fork.

**En contra:** un perfil mentiroso arruina la ventaja. De ahí la regla de
"ningún valor sin código y test", que es la única cosa que impide que esta
tabla se convierta en el paper otra vez.
