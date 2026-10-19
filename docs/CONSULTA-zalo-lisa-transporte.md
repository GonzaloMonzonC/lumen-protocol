# Consulta a Zalo y Lisa — formato canónico y transporte entre nodos

**Fecha:** 2026-10-19 · **Consultados:** Zalo (`/v1/chat`, HMAC) y Lisa (`/v1/chat`)
**Método:** los tres docs de propuesta enviados como preguntas cortas (≤800 chars, según `a2a-communication`)
**Verificación:** cada afirmación técnica de Zalo comprobada contra el código del repo.

---

## 1. Formato canónico — consenso

**Zalo: `frame.rs`.** Sus razones, y coinciden con la propuesta:

> *"Es el único formato de la spec: Hyb128 + type + flags + payload, diccionario estático + sesión,
> 12 tipos de frame y handshake PROBE/ACK.
> `shm.rs` (magic LUME): zero-copy **intra-nodo**. No cruza un socket ni sirve entre máquinas.
> `lumen_transport.py` (LUM01 + zlib): shim Python antiguo. Sin negociación ni tipos de frame, y zlib
> añade dependencia + CPU.
> `frame.rs` es little-endian fijo, sin padding ni compresor externo → mismo comportamiento en
> Windows/Linux/Mac."*

**Aporte que yo no tenía:** *"`lumen-mcp` ya lo implementa (`frame.py`, `frame_assembler.py`,
`negotiation.py`), incluido el fix de pipes de Windows."*

✅ **Verificado en el repo:** existen `implementations/python/src/lumen/frame.py`, `frame_assembler.py`,
`negotiation.py`. **La implementación Python del canónico ya está escrita** — no hay que crearla.

**Plan de migración que propone Zalo:**
> *"`shm` como fast-path local con fallback a frame; LUM01 deprecado tras shim; conexiones nuevas negocian
> PROBE/ACK y, si falla, JSON-RPC."*

Esto coincide con la arquitectura de 3 capas de la propuesta: SHM local → frame entre nodos → JSON-RPC fallback.

**Lisa:** no aportó criterio técnico. Sus dos respuestas fueron genéricas
(*"LUMEN es el protocolo cognitivo con SHM zero-copy y PDB..."*) incluso tras reformular la pregunta.
**Se descarta su consulta** — está en bucle de respuesta de memoria, no analítica. No es un fallo de la
pregunta: la segunda fue directa y específica.

---

## 2. Transporte — Zalo recomienda QUIC, y avisa de tres riesgos serios

> *"**Recomendación: QUIC como canónico entre nodos (Nivel 4).**
> Riesgos QUIC: cliente no verifica certificados → **cifrado sin autenticación**. Cualquiera con un cert
> autofirmado se hace pasar por nodo. MITM trivial en red no confiable. 0-RTT → early data **replayable** y
> sin forward secrecy. Solo para mensajes idempotentes. Nunca para mutaciones. Superficie DoS: reensamblaje
> de fragmentos y creación de canales sin límites negociados.
> **Mitigación obligatoria:** verificación con pinning o CA propia + **macaroons mutuos**. 0-RTT off por
> defecto o restringido.
> HTTP + LUMEN encima: doble encuadre y cabeceras, tiras la compresión semántica y el O(1) skipping que
> justifican LUMEN; flow control HTTP/2 añade cola. Útil como **fallback corporativo, no como canon**."*

### Verificación en código de sus tres afirmaciones

| Afirmación de Zalo | Verificado | Evidencia |
|---|---|---|
| El cliente NO verifica certificados | ✅ **CIERTO** | `quic.rs:43` — `struct SkipCertVerifier` implementa `ServerCertVerifier` con `verify_server_cert` que no verifica nada |
| 0-RTT activado y sin restricción | ✅ **CIERTO** | `quic.rs:103,123,394,417` — `max_early_data_size = u32::MAX` y `enable_early_data = true` |
| X25519 no autentica | ✅ **CIERTO** | `crypto.rs:36` — *"X25519 key exchange provides encryption but NOT authentication. Without an external authentication mechanism... vulnerable to MITM"* |

**No se equivocó en nada.** Y coincide con el propio código, que ya lo avisaba.

### El detalle que aporta y yo no tenía: **macaroons**

> *"el doc ya dice que X25519 solo no autentica"* y propone **macaroons mutuos** como autenticación.

✅ El repo **tiene** `implementations/rust/src/macaroon.rs`. **La pieza de autenticación ya existe** — no hay
que inventar PKI. Esto convierte el bloqueante "QUIC sin verificación de certs" en algo resoluble con código
presente: **macaroons en vez de PKI para autenticar nodos.**

---

## 3. Consenso y correcciones a la propuesta

| Punto | Propuesta original | Consenso Zalo | Estado |
|---|---|---|---|
| Formato canónico | `frame.rs` | **`frame.rs`** | ✅ ratificado |
| `shm.rs` | fast-path local | **intra-nodo, no cruza socket** | ✅ ratificado, con matiz |
| `lumen_transport.py` | linaje "legacy" | **shim antiguo, deprecar** | ✅ ratificado |
| Transporte | QUIC + fallback HTTP | **QUIC canónico, HTTP fallback** | ✅ ratificado |
| Autenticación QUIC | "falta verificación" | **macaroons mutuos + pinning** | 🔧 **mejora concreta** |
| 0-RTT | ventaja | **riesgo de replay: solo idempotentes** | 🔧 **corrección** |
| Implementación Python | "hay que migrar" | **ya existe `frame.py`/`negotiation.py`** | 🎯 **ahorra trabajo** |

### Tres cosas que cambian el plan

1. **No hay que escribir el framing Python.** `lumen/frame.py` + `negotiation.py` + `frame_assembler.py` ya
   existen. La Fase 1 baja de "implementar" a "conectar".
2. **La autenticación se resuelve con macaroons**, no con PKI. `macaroon.rs` ya está.
3. **0-RTT no es una ventaja libre.** `max_early_data_size = u32::MAX` es un riesgo real: restringirlo a
   frames idempotentes (`PROBE`) y apagarlo para mutaciones.

---

## 4. Lo que sigue sin resolver (y verifiqué yo)

### ⚠️ La MVM solo sabe hablar MCP por HTTP

`host.rs` — las tres acciones MCP usan la **misma** función:

```rust
"tools" => mcp_http_request(&url, "tools/list", ...),
"ping"  => mcp_http_request(&url, "initialize", ...),
"call"  => mcp_http_request(...),
```

**No existe rama QUIC ni LUMEN.** El campo `^SYS("MCP",server,"type")` se lee y se reporta en `mcp:list`,
**pero no se usa para elegir transporte** — el código siempre va a `mcp_http_request`.

Es decir: **la decisión "QUIC canónico" no está implementada en el consumidor (MVM).** El `quic.rs` existe como
librería, pero `host.rs` no la llama. **Ese es el trabajo real de la Fase 1.**

| pieza | estado |
|---|---|
| `quic.rs` (cliente/servidor QUIC) | ✅ existe |
| `frame.rs` (framing) | ✅ existe |
| `macaroon.rs` (autenticación) | ✅ existe |
| `lumen/frame.py` + `negotiation.py` | ✅ existe (Zalo lo confirmó) |
| **`host.rs` → transportar `mcp:call` por QUIC** | ❌ **NO existe** — hoy solo `mcp_http_request` |

### Lisa no es fiable para arquitectura

Dos intentos, dos respuestas de memoria (*"LUMEN es el protocolo cognitivo con SHM zero-copy y PDB..."*),
incluso con la segunda pregunta reformulada y muy específica. **No es un fallo de la pregunta.**
Para consultas técnicas: **Zalo (KB completa) + verificación en código**. Lisa para planificación/orquestación.

---

## Conclusión

**Zalo ratifica las tres decisiones y aporta dos mejoras que ahorran trabajo** (framing Python ya existe,
macaroons ya existen) **y una corrección de seguridad** (0-RTT replayable).

La propuesta de transporte queda así:

```
SHM (mismo host)  →  frame.rs sobre QUIC (entre nodos)  →  JSON-RPC (fallback)
                     + macaroons mutuos
                     + 0-RTT solo en PROBE/discovery
```

Y el orden de trabajo cambia un poco, ahora que sabemos qué falta exactamente:

| # | paso | estado |
|---|---|---|
| **Fase 0** | canónico = `frame.rs` | ✅ **decidido** (propuesta + Zalo) |
| **1a** | puerto de `frame.py`/`negotiation.py` a los servers | 🎯 ya existe el código; falta conectar |
| **1b** | **`host.rs`: `mcp:call` por QUIC** (hoy solo `mcp_http_request`) | ❌ **el trabajo real** |
| 2 | macaroons mutuos + pinning + 0-RTT restringido | 🎯 `macaroon.rs` ya existe |
| 3 | `^TOOLS_AGENTE` (capa 2 de la MVM) | pendiente |

**El cuello de botella ya no es "decidir el protocolo" — es que el consumidor (la MVM) solo sabe HTTP.**
Todo lo demás está escrito en el repo.
