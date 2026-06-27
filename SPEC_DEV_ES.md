# Especificación del Protocolo LUMEN v1.0-draft — Español

> **L**ightweight **U**niversal **M**odel **E**xchange **N**etwork
> (Red Universal Ligera de Intercambio de Modelos)

---

## 1. Visión general y filosofía

### 1.1 El problema de JSON-RPC

MCP (Model Context Protocol) usa JSON-RPC 2.0 como capa de mensajería. Aunque funcional, tiene deficiencias:

| Problema | Impacto |
|----------|---------|
| Claves repetidas por mensaje (`jsonrpc`, `id`, `method`) | ~40–60 bytes de overhead fijo |
| Parseo texto (UTF-8 → DOM → tipos nativos) | Penalización de CPU en cada endpoint |
| Sin compresión nativa de claves | Las mismas strings se re-serializan millones de veces |
| Sin soporte de token streaming | Cada token LLM requiere un frame JSON completo |
| Sin zero-copy | Los payloads se copian entre buffers durante serialización/deserialización |
| Sin zero-trust | Sin mecanismo de atenuación de permisos entre agentes |

### 1.2 Principios de diseño de LUMEN

1. **Local-first**: El perfil primario es IPC local (stdio, UDS). La web es secundaria.
2. **Zero-copy siempre que sea posible**: Los payloads se referencian, no se copian.
3. **Zero-trust by design**: Cada endpoint lleva sus propios Capability Tokens atenuables.
4. **Pagar solo por lo que se usa**: Sin columnas fijas para features opcionales (MUX, encriptación).
5. **O(1) en el hot path**: El parser de headers nunca itera en modos comunes.
6. **Auto-delimitante**: Los frames no dependen de delimitadores externos (`\n`, framing HTTP).

---

## 2. Abstracción de Transporte (LTA)

LUMEN es **agnóstico de transporte**, pero requiere un contrato mínimo por nivel.

### 2.1 Nivel 1 — Stream (obligatorio)

```
Requisitos:
  ✅ Ordenamiento garantizado (FIFO)
  ✅ Sin pérdida de bytes
  ✅ Full-duplex

Transportes que lo satisfacen:
  • stdio (pipes stdin/stdout)
  • Unix Domain Sockets (SOCK_STREAM)
  • Named Pipes (Windows)
  • TCP
  • WebSocket (frames binarios)
```

Este es el nivel base. Toda implementación LUMEN **debe** soportar Nivel 1.

### 2.2 Nivel 2 — Zero-Copy (implementado en Rust)

```
Requisitos adicionales:
  ✅ Todo lo del Nivel 1
  ✅ Memoria compartida entre endpoints (mmap / shm en Unix, CreateFileMapping en Windows)
  ✅ Frames sin serialización (casts directos en memoria via ring buffers)
  ✅ Negociación in-band con TYPE_TRANSPORT_INIT (0x0B) / TYPE_TRANSPORT_ACK (0x0C)

Transportes que lo satisfacen:
  • Unix: shm_open + mmap (MAP_SHARED) con path tipo /lumen-shm-<ts>-<pid>
  • Windows: CreateFileMappingW + MapViewOfFile con nombre único
  • WASM: no soportado (stub que devuelve Unsupported)

Arquitectura ring buffer:
  ┌─────────────────────────────────────────────────────────────┐
  │ Header (128 bytes): magic="LUME", version=1, layout info    │
  │   Ring A: write_a cursor (client), read_a cursor (server)   │
  │   Ring B: write_b cursor (server), read_b cursor (client)   │
  ├─────────────────────────────────────────────────────────────┤
  │ Ring A data: Client → Server  (~256 KiB)                    │
  │ Ring B data: Server → Client  (~256 KiB)                    │
  └─────────────────────────────────────────────────────────────┘
  Tamaño por defecto: 512 KiB total. SPSC lock-free con AtomicU64.
  Cada frame lleva prefijo de 4 bytes LE con la longitud.
```

Negociación:
```
Client → Server:  TYPE_TRANSPORT_INIT (0x0B) → { "caps": ["mmap","stdio"] }
Server → Client:  TYPE_TRANSPORT_ACK  (0x0C) → { "cap":"mmap",
                                                     "shm_path":"/lumen-shm-<ts>-<pid>",
                                                     "shm_size":524288 }
```

Si el handshake falla o mmap no está disponible, degrada automáticamente a Nivel 1.

### 2.3 Nivel 3 — Datagrama (implementado)

```
Requisitos adicionales:
  ✅ Todo lo del Nivel 1
  ✅ UDP unicast (send_to / recv_from)
  ✅ Modo non-blocking
  ✅ IPv4 multicast (join/leave, TTL configurable, loopback)
  ✅ Cada datagrama = exactamente 1 frame LUMEN completo

Garantías:
  ❌ Sin garantía de orden
  ❌ Sin garantía de entrega
  ❌ Sin supresión de duplicados

Transportes que lo satisfacen:
  • UDP (std::net::UdpSocket en Rust, node:dgram en TypeScript)
  • IPv4 multicast (239.0.0.0/8, TTL por defecto = 1)

Límites:
  • MAX_DATAGRAM_SIZE = 65507 bytes (65535 − 8 UDP − 20 IP)
  • MAX_FRAME_PAYLOAD  = 65500 bytes (MAX_DATAGRAM_SIZE − 7 overhead Hyb128+TYPE+FLAGS)

Casos de uso:
  • Telemetría / métricas (fire-and-forget)
  • Heartbeats (keep-alive best-effort)
  • Envío de logs (alto throughput, tolerante a pérdidas)
  • Service discovery (frames multicast DISCOVER)
```

```
Arquitectura:

┌─────────────────────────────────────────────────┐
│ DatagramTransport                               │
│   socket: UdpSocket (non-blocking)              │
│   recv_buf: [u8; 65507]                         │
│                                                 │
│   bind(addr)         → Self                     │
│   connect(local,remote) → Self (connected UDP)   │
│   send_frame_to(fr,addr) → bytes sent           │
│   recv_frame()       → Option<(&[u8], SrcAddr)> │
│   join_multicast(maddr, iface)                  │
│   set_multicast_ttl(ttl)                        │
│   set_multicast_loop(on/off)                    │
└─────────────────────────────────────────────────┘

Benchmarks incluidos (bin/dgram-shootout.rs):
  S1: Latencia roundtrip (ping-pong), payloads 16B → 65KB
  S2: Throughput unidireccional (fire-and-forget)
  S3: Heartbeat ping-pong (payload 8B)
  S4: Overhead de parseo de frame (build → send → recv → parse)
  S5: Stress test de payload máximo (65500B payload, 100 frames)

TypeScript: DatagramTransport en src/dgram.ts (node:dgram).
  13 tests: bind, send/recv unicast, múltiples frames, parseo, close, payload binario.
```

---

## 3. Anatomía del Frame

### 3.1 Estructura general

```
┌──────────────────────────────────────────────────────────┐
│ [LEN:Hyb128] [TYPE:1B] [FLAGS:1B] [PAYLOAD:LEN bytes]   │
└──────────────────────────────────────────────────────────┘

Overhead mínimo: 3 bytes (payload 0–63 B)
Overhead típico: 4 bytes (payload 64 B–64 KB)
Overhead máximo: 12 bytes (payload > 4 GB, LEB128)
```

### 3.2 Hyb128 — Codificación de longitud híbrida

El primer byte del frame codifica la longitud del payload en sus 2 bits superiores:

```
Byte 0: [MODE:2bits] [VALUE:6bits]
```

| Modo | Bits | Decodificación | Total bytes | Rango |
|------|------|---------------|-------------|-------|
| `00` | `00xxxxxx` | Los 6 bits bajos son la longitud | **1** | 0–63 |
| `01` | `01xxxxxx` | Bytes siguientes en LEB128 | **2–11** | > 4 GB |
| `10` | `10xxxxxx` | Siguientes 2 bytes como u16 little-endian | **3** | 64–65535 |
| `11` | `11xxxxxx` | Siguientes 4 bytes como u32 little-endian | **5** | 65536–4294967295 |

#### Propiedad O(1)

Para los modos `00`, `10` y `11`, el parser sabe **en una sola lectura de CPU** cuántos bytes adicionales debe leer:

```
mode = first_byte >> 6;

switch (mode) {
    0b00: len = first_byte & 0x3F;           skip = 0;
    0b10: len = read_u16_le(buf[1..3]);      skip = 2;
    0b11: len = read_u32_le(buf[1..5]);      skip = 4;
    0b01: len = leb128_decode(&buf[1..]);    skip = variable;
}
```

No hay loops en el hot path. Aproximadamente el 90% de los mensajes MCP caen en modos `00` o `10`.

> **Implementación de referencia**: [`hyb128.rs`](implementations/rust/src/hyb128.rs)

### 3.3 Header fijo (TYPE + FLAGS)

Inmediatamente después de Hyb128:

```
[TYPE:1B] [FLAGS:1B]
```

**TYPE** — identifica la semántica del frame:

| ID | Constante | Dirección | Descripción |
|----|-----------|-----------|-------------|
| `0x01` | `REQUEST` | C→S, S→C | Request esperando respuesta |
| `0x02` | `RESPONSE` | S→C, C→S | Respuesta a un REQUEST |
| `0x03` | `NOTIFY` | ↔ | Fire-and-forget, sin respuesta |
| `0x04` | `STREAM_DATA` | ↔ | Chunk de datos para un stream activo |
| `0x05` | `SCHEMA_PATCH` | ↔ | Delta de schema (agregar/quitar tools, resources) |
| `0x06` | `STREAM_INIT` | ↔ | Inicializa un token stream |
| `0x07` | `DICT_SYNC` | ↔ | Sincronización de diccionario de sesión |
| `0x08` | `DISCOVER` | ↔ | Introspección dinámica (late binding) |
| `0x09` | `MUX` | ↔ | Wrapper de multiplexación |
| `0x0A` | `HEARTBEAT` | ↔ | Keep-alive |
| `0x0B` | `TRANSPORT_INIT` | C→S | Inicio de negociación de capacidades de transporte (§2.2) |
| `0x0C` | `TRANSPORT_ACK` | S→C | ACK de negociación de capacidades de transporte (§2.2) |
| `0x0D–0x0E` | *Reservado* | — | Para expansión futura |
| `0x0F` | `PROBE` | C→S | Sonda de negociación de protocolo (puede llevar clave pública X25519) |
| `0x10` | `PROBE_ACK` | S→C | ACK de negociación de protocolo (puede llevar clave pública X25519) |
| `0x11+` | *Reservado* | — | Para expansión futura |

**FLAGS** — bitmask de 8 bits:

| Bit | Constante | Significado |
|-----|-----------|-------------|
| `0x01` | `COMPRESSED` | Payload comprimido con el diccionario LUMEN |
| `0x02` | `ENCRYPTED` | Payload encriptado |
| `0x04` | `PRIORITY` | Frame prioritario (salta colas) |
| `0x08` | `FRAGMENTED` | Frame fragmentado (continuación en el próximo frame) |
| `0x10–0x80` | *Reservado* | Para expansión futura |

---

## 4. Workflow y Multiplexación

### 4.1 Ciclo de vida del Request

```
Client                                Server
  │                                       │
  │──── REQUEST (id=1, method="tool") ───→│
  │                                       │ process...
  │←─── RESPONSE (id=1, result=...) ─────│
  │                                       │
```

- Cada `REQUEST` lleva un `id` (ID de diccionario `0x04`).
- El `RESPONSE` repite el `id` para correlacionar.
- `NOTIFY` no lleva `id` y no espera respuesta.

### 4.2 Multiplexación (MUX)

El frame `0x09 MUX` encapsula otro frame LUMEN en un canal lógico:

```
MUX Frame:
┌──────────────────────────────────────────────────────────────┐
│ [LEN:Hyb128] [0x09] [FLAGS]                                  │
│ [CHANNEL:1B] [CTRL:4b] [RESERVED:4b]                        │
│ [INNER: frame LUMEN completo]                                 │
└──────────────────────────────────────────────────────────────┘

Bits CTRL:
  bit0: OPEN  — Crear canal lógico
  bit1: CLOSE — Cerrar canal lógico
  bit2: PAUSE — Backpressure (pausar envío)
  bit3: RESUME — Reanudar envío
```

- **Sin overhead en frames normales**: MUX solo se paga cuando se usa.
- **256 canales lógicos** sobre una sola conexión física.
- **Control de flujo por canal**: Evita head-of-line blocking.

### 4.3 TokenStream — Streaming nativo para LLMs

```
Inicialización:
┌────────────────────────────────────────────┐
│ [0x06] [FLAGS]                             │
│ [STREAM_ID:2B] [TOKEN_TYPE:1B]             │
└────────────────────────────────────────────┘

TOKEN_TYPE:
  0x00 = tokens UTF-8 texto
  0x01 = IDs de token u16
  0x02 = IDs de token u32
  0x03 = embeddings f32 (4 bytes)

Bursts de datos:
┌────────────────────────────────────────────┐
│ [0x04] [FLAGS]                             │
│ [STREAM_ID:2B] [BURST_LEN:Hyb128] [TOKENS] │
└────────────────────────────────────────────┘

Cierre: BURST_LEN = 0 en STREAM_DATA
```

---

## 5. Compresión Semántica (Dictionaries)

### 5.1 Arquitectura

```
Sin comprimir:  {"tool": "search", "arguments": {"query": "hola"}}
Comprimido:    {0x00: "search", 0x01: {lookup("query"): "hola"}}
```

### 5.2 Diccionario Estático (IDs `0x00–0x7F`)

128 entradas predefinidas. **Nunca cambian.** → Ver [`DICTIONARY.md`](DICTIONARY.md).

### 5.3 Diccionario de Sesión (IDs `0x80–0xFE`)

127 entradas negociadas durante el handshake, actualizables via `DICT_SYNC` (`0x07`):

```
Payload DICT_SYNC:
[OP:1B] [ENTRY_COUNT:1B] [ENTRIES...]

OP:
  0x00 = ADD
  0x01 = REMOVE
  0x02 = REPLACE

ENTRY: [ID:1B] [KEY_LEN:1B] [KEY:N]
```

API disponible en los 5 lenguajes: `register_session_key`, `unregister_session_key`,
`init_session_dict`, `clear_session_dict`, `session_dict_size`.

### 5.4 Sincronización

```
Client: "Mi dict v3, 142 entradas"
Server: "Tengo v3 con 140. Enviando delta."
          → SCHEMA_PATCH ADD entradas 141, 142
Client: "ACK dict completa v3 (142 entradas)"
```

### 5.5 ID 0xFF — Clave sin comprimir

Cuando una clave no está en ningún diccionario, se transmite como texto plano.

---

## 6. Late Binding — Descubrimiento Dinámico

### 6.1 DISCOVER (0x08)

```
DISCOVER Request:  [0x08] [FLAGS] [SCOPE:1B]
SCOPE:
  0x00 = All (tools + resources + prompts + capabilities)
  0x01 = Solo tools
  0x02 = Solo resources
  0x03 = Solo capabilities

DISCOVER Response: [0x02] [FLAGS] [SCOPE:1B] [SCHEMA...]
```

La respuesta puede ser **incremental** (solo lo nuevo desde la última sincronización).

---

## 7. Seguridad Integrada (Zero-Trust)

### 7.1 Handshake

```
Client → Server:
  REQUEST { version: 1, capabilities: ["stream"], macaroon: "<token>" }
```

### 7.2 Capability Tokens (Macaroons)

```yaml
caveats:
  - op: "filesystem.read:/home/user/project"
  - op: "tool.call:search_code"
  - exp: "2026-06-11T18:00:00Z"
  - rate: "100/min"
```

### 7.3 Atenuación

Un nodo puede **restringir aún más** un Macaroon sin invalidar la firma:

```
Orchestrator recibe: op: filesystem.read:/
Delega a sub-agent:   op: filesystem.read:/home/user/project/src  ← atenuado
Sub-agent NO PUEDE:  ❌ Leer /etc/passwd
```

### 7.4 Encriptación wire (ChaCha20-Poly1305 + X25519)

LUMEN soporta **encriptación de frame autenticada** usando ChaCha20-Poly1305 AEAD
con intercambio de claves X25519. La encriptación es opcional y se negocia durante el
handshake PROBE/PROBE_ACK.

#### 7.4.1 Formato de payload encriptado

Cuando `FLAG_ENCRYPTED` (0x02) está activo, el payload del frame contiene:

```
┌──────────────────────────────────────────────────────────────┐
│ [NONCE:12B] [CIPHERTEXT:N bytes] [TAG:16B]                   │
└──────────────────────────────────────────────────────────────┘

Overhead total: 28 bytes (12B nonce + 16B tag Poly1305)
```

El frame completo en el wire:

```
┌──────────────────────────────────────────────────────────────┐
│ [Hyb128:LEN] [TYPE:1B] [FLAGS:1B | 0x02] [payload_encriptado] │
└──────────────────────────────────────────────────────────────┘
```

#### 7.4.2 Nonce

Nonce ChaCha20-Poly1305 de 96 bits (12 bytes):

```
[NONCE:12B] = [COUNTER:u64 LE][ZEROS:4B]
```

- **Contador**: Monotónicamente creciente, independiente por dirección
  (client→server y server→client arrancan en 0).
- **Zeros**: 4 bytes cero para prevenir colisiones.

El receptor **DEBE** rechazar frames con un nonce menor o igual al último nonce recibido
(protección anti-replay).

#### 7.4.3 Intercambio de claves (X25519)

```
Client                               Server
  │                                      │
  │ 1. Genera keypair X25519             │
  │ 2. PROBE { pk: <pubkey_b64> } ────→│
  │                                      │ 3. Genera keypair X25519
  │                                      │ 4. Deriva shared secret
  │ 5. Deriva shared secret             │
  │ 6. PROBE_ACK { pk: <pubkey_b64> } ←─│
  │                                      │
  │  ◄══════ frames encriptados ═════════►│
```

- Cada lado genera un keypair **efímero** X25519 (no se reutiliza entre sesiones).
- El shared secret de 32 bytes se usa directamente como clave ChaCha20-Poly1305.
- Claves públicas (32 bytes) se codifican en **base64** dentro del JSON de PROBE/PROBE_ACK.
- Si el server no incluye `pk` en su ACK, la encriptación **no se negocia** y la comunicación
  continúa en texto plano.

#### 7.4.4 API

```rust
// Rust
use lumen::crypto::{Keypair, Cipher};

let kp = Keypair::generate();
let shared = kp.derive_shared_secret(&peer_public);
let mut cipher = Cipher::new(&shared);

let frame = cipher.build_encrypted_frame(TYPE_REQUEST, 0, b"payload");
// ... enviar frame ...
// ... recibir encrypted_payload ...
let plaintext = cipher.decrypt(encrypted_payload).unwrap();
```

```typescript
// TypeScript (Web Crypto API)
import { generateKeypair, deriveSharedSecret, Cipher } from "@lumen/mcp-transport";

const kp = await generateKeypair();
const shared = await deriveSharedSecret(kp.secretKey, peerPublicKey);
const cipher = new Cipher();
await cipher.init(shared);

const frame = await cipher.buildEncryptedFrame(TYPE_REQUEST, 0, payload);
const plaintext = await cipher.decrypt(encryptedPayload);
```

#### 7.4.5 Garantías

| Propiedad | Mecanismo |
|-----------|-----------|
| **Confidencialidad** | ChaCha20 (stream cipher, clave 256-bit) |
| **Integridad** | MAC Poly1305 (autentica nonce + ciphertext) |
| **Anti-replay** | Contador de nonce monotónico (receptor rechaza duplicados) |
| **Perfect forward secrecy** | Keypairs X25519 efímeros (no PFS perfecta, pero efímera por sesión) |
| **Sin certificados** | Trust-on-first-use (TOFU) via PROBE/PROBE_ACK |

> ⚠️ **Limitación actual:** No hay PKI ni verificación de identidad. La encriptación protege
> contra eavesdropping pasivo y MITM activo (gracias a AEAD), pero no autentifica la identidad
> del peer. Para autenticación mutua, combinar con Macaroons (§7.2).

### 7.5 Implementaciones

| Lenguaje | Módulo | Encriptación | Intercambio de claves |
|---|:---:|:---:|:---:|
| **Rust** | `crypto.rs` | ✅ ChaCha20-Poly1305 | ✅ X25519 |
| **TypeScript** | `crypto.ts` | ✅ ChaCha20-Poly1305 (WebCrypto) | ✅ X25519 (WebCrypto) |
| **Python** | *(pendiente)* | — | — |
| **C#** | *(pendiente)* | — | — |
| **PHP** | *(pendiente)* | — | — |

---

## 8. Tablas de Referencia

### 8.1 Tipos de Frame

| ID | Tipo | Overhead adicional |
|----|------|-------------------|
| `0x01` | REQUEST | 0 |
| `0x02` | RESPONSE | 0 |
| `0x03` | NOTIFY | 0 |
| `0x04` | STREAM_DATA | 2B (stream_id) + Hyb128 (burst_len) |
| `0x05` | SCHEMA_PATCH | 2B (op + count) |
| `0x06` | STREAM_INIT | 3B (stream_id + token_type) |
| `0x07` | DICT_SYNC | 2B (dict_version) |
| `0x08` | DISCOVER | 1B (scope) |
| `0x09` | MUX | 2B (channel + ctrl) |
| `0x0A` | HEARTBEAT | 0 |

### 8.2 Flags

| Bit | Máscara | Nombre |
|-----|---------|-------|
| 0 | `0x01` | COMPRESSED |
| 1 | `0x02` | ENCRYPTED |
| 2 | `0x04` | PRIORITY |
| 3 | `0x08` | FRAGMENTED |

> `ENCRYPTED` (bit 1, 0x02): El payload contiene un blob encriptado con ChaCha20-Poly1305.
> Ver §7.4 para el formato completo de encriptación y handshake X25519.

---

## 9. Referencias

- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
- [Macaroons: Cookies with Contextual Caveats](https://research.google.com/pubs/pub41892/)
- [Codificación LEB128](https://en.wikipedia.org/wiki/LEB128)
- Implementación de referencia: [`implementations/rust/`](implementations/rust/)
- Bindings WASM: `wasm-pack build --target web --features wasm` → `pkg/lumen.js`

---

*LUMEN v0.1.0 — Última actualización: 2026-06-14*
