# LUMEN — Protocol Specification v1.0-draft

> **L**ightweight **U**niversal **M**odel **E**xchange **N**etwork

---

## 1. Visión General y Filosofía

### 1.1 El problema de JSON-RPC

MCP (Model Context Protocol) utiliza JSON-RPC 2.0 como capa de mensajería. Aunque funcional, presenta deficiencias:

| Problema | Impacto |
|----------|---------|
| Claves repetidas por mensaje (`jsonrpc`, `id`, `method`) | ~40–60 bytes de overhead fijo |
| Parseo de texto (UTF-8 → DOM → tipos nativos) | Penalización de CPU en cada extremo |
| Sin compresión nativa de claves | Mismas cadenas re-serializadas millones de veces |
| Sin soporte de streaming de tokens | Cada token de LLM requiere un frame JSON completo |
| Sin zero-copy | Payloads copiados entre buffers al serializar/deserializar |
| Sin zero-trust | Sin mecanismo de atenuación de permisos entre agentes |

### 1.2 Principios de diseño de LUMEN

1. **Local-first**: El perfil primario es IPC local (stdio, UDS). La web es secundaria.
2. **Zero-copy siempre que sea posible**: Los payloads se referencian, no se copian.
3. **Zero-trust por diseño**: Cada extremo porta sus propios Capability Tokens atenuables.
4. **Pagar solo por lo que se usa**: Sin columnas fijas para features opcionales (MUX, cifrado).
5. **O(1) en el camino caliente**: El parser de cabeceras nunca itera para modos comunes.
6. **Autodelimitado**: Los frames no dependen de delimitadores externos (`\n`, HTTP framing).

---

## 2. Abstracción de Transporte (LTA)

LUMEN es **agnóstico al transporte**, pero exige un contrato mínimo según el nivel.

### 2.1 Nivel 1 — Stream (obligatorio)

```
Requisitos:
  ✅ Orden garantizado (FIFO)
  ✅ Sin pérdida de bytes
  ✅ Full-duplex

Transportes que lo cumplen:
  • stdio (stdin/stdout pipes)
  • Unix Domain Sockets (SOCK_STREAM)
  • Named Pipes (Windows)
  • TCP
  • WebSocket (binary frames)
```

Este es el nivel base. Cualquier implementación de LUMEN **debe** soportar Nivel 1.

### 2.2 Nivel 2 — Zero-Copy (implementado en Rust)

```
Requisitos adicionales:
  ✅ Todo lo del Nivel 1
  ✅ Memoria compartida entre extremos (mmap / shm en Unix, CreateFileMapping en Windows)
  ✅ Frames sin serializar (cast directo de memoria via ring buffers)
  ✅ Negociación in-band con TYPE_TRANSPORT_INIT (0x0B) / TYPE_TRANSPORT_ACK (0x0C)

Transportes que lo cumplen:
  • Unix: shm_open + mmap (MAP_SHARED) con path tipo /lumen-shm-<ts>-<pid>
  • Windows: CreateFileMappingW + MapViewOfFile con nombre único
  • WASM: no soportado (stub que devuelve Unsupported)

Arquitectura de ring buffer:
  ┌─────────────────────────────────────────────────────────────┐
  │ Header (128 bytes): magic="LUME", version=1, layout info    │
  │   Ring A: write_a cursor (cliente), read_a cursor (servidor)│
  │   Ring B: write_b cursor (servidor), read_b cursor (cliente)│
  ├─────────────────────────────────────────────────────────────┤
  │ Ring A data: Client → Server  (~256 KiB)                    │
  │ Ring B data: Server → Client  (~256 KiB)                    │
  └─────────────────────────────────────────────────────────────┘
  Región por defecto: 512 KiB total. SPSC lock-free con AtomicU64.
  Cada frame se prefija con 4 bytes LE de longitud.
```

Negociación:
```
Cliente → Servidor:  TYPE_TRANSPORT_INIT (0x0B) → { "caps": ["mmap","stdio"] }
Servidor → Cliente:  TYPE_TRANSPORT_ACK  (0x0C) → { "cap":"mmap",
                                                     "shm_path":"/lumen-shm-<ts>-<pid>",
                                                     "shm_size":524288 }
```

Si el handshake falla o mmap no está disponible, se degrada automáticamente a Nivel 1.

### 2.3 Nivel 3 — Datagram (experimental)

```
Requisitos:
  ❌ Sin garantía de orden
  ❌ Sin garantía de entrega

Transportes: UDP, multicast
```

Cada datagrama contiene exactamente un frame LUMEN. Solo para telemetría, logs o heartbeats.

---

## 3. Anatomía del Frame

### 3.1 Estructura general

```
┌──────────────────────────────────────────────────────────┐
│ [LEN:Hyb128] [TYPE:1B] [FLAGS:1B] [PAYLOAD:LEN bytes]   │
└──────────────────────────────────────────────────────────┘

Overhead mínimo: 3 bytes (payload 0–63 B)
Overhead típico:  4 bytes (payload 64 B–64 KB)
Overhead máximo: 12 bytes (payload > 4 GB, LEB128)
```

### 3.2 Hyb128 — Encoding híbrido de longitud

El primer byte del frame codifica la longitud del payload en sus 2 bits superiores:

```
Byte 0: [MODE:2bits] [VALUE:6bits]
```

| Mode | Bits | Decodificación | Bytes totales | Rango |
|------|------|----------------|---------------|-------|
| `00` | `00xxxxxx` | Los 6 bits bajos son la longitud | **1** | 0–63 |
| `01` | `01xxxxxx` | Siguientes bytes en LEB128 | **2–11** | > 4 GB |
| `10` | `10xxxxxx` | Siguientes 2 bytes en little-endian u16 | **3** | 64–65535 |
| `11` | `11xxxxxx` | Siguientes 4 bytes en little-endian u32 | **5** | 65536–4294967295 |

#### Propiedad O(1)

Para los modos `00`, `10` y `11`, el parser sabe **en una sola lectura de CPU** cuántos bytes adicionales leer:

```
mode = first_byte >> 6;

switch (mode) {
    0b00: len = first_byte & 0x3F;           skip = 0;
    0b10: len = read_u16_le(buf[1..3]);      skip = 2;
    0b11: len = read_u32_le(buf[1..5]);      skip = 4;
    0b01: len = leb128_decode(&buf[1..]);    skip = variable;
}
```

No hay bucles en el camino caliente. El ~90% de los mensajes MCP caen en modos `00` o `10`.

> **Implementación de referencia**: [`hyb128.rs`](implementations/rust/src/hyb128.rs)

### 3.3 Cabecera fija (TYPE + FLAGS)

Inmediatamente después del Hyb128:

```
[TYPE:1B] [FLAGS:1B]
```

**TYPE** — identifica la semántica del frame:

| ID | Constante | Dirección | Descripción |
|----|-----------|-----------|-------------|
| `0x01` | `REQUEST` | C→S, S→C | Petición que espera respuesta |
| `0x02` | `RESPONSE` | S→C, C→S | Respuesta a un REQUEST |
| `0x03` | `NOTIFY` | ↔ | Fire-and-forget, sin respuesta |
| `0x04` | `STREAM_DATA` | ↔ | Chunk de datos de un stream activo |
| `0x05` | `SCHEMA_PATCH` | ↔ | Delta de esquema (add/remove tools, resources) |
| `0x06` | `STREAM_INIT` | ↔ | Inicializa un stream de tokens |
| `0x07` | `DICT_SYNC` | ↔ | Sincronización del diccionario de sesión |
| `0x08` | `DISCOVER` | ↔ | Introspección dinámica (late binding) |
| `0x09` | `MUX` | ↔ | Envoltorio de multiplexación |
| `0x0A` | `HEARTBEAT` | ↔ | Keep-alive |
| `0x0B` | `TRANSPORT_INIT` | C→S | Transport capability negotiation init (§2.2) |
| `0x0C` | `TRANSPORT_ACK` | S→C | Transport capability negotiation ack (§2.2) |
| `0x0D–0x0F` | *Reservados* | — | Para futura expansión |
| `0x0F` | `PROBE` | C→S | Protocol-level negotiation probe (TS-only) |
| `0x10` | `PROBE_ACK` | S→C | Protocol-level negotiation ack (TS-only) |
| `0x10+` | *Reservados* | — | Para futura expansión |

**FLAGS** — bitmask de 8 bits:

| Bit | Constante | Significado |
|-----|-----------|-------------|
| `0x01` | `COMPRESSED` | Payload comprimido con el diccionario LUMEN |
| `0x02` | `ENCRYPTED` | Payload cifrado |
| `0x04` | `PRIORITY` | Frame prioritario (saltar colas) |
| `0x08` | `FRAGMENTED` | Frame fragmentado (continuación en siguiente) |
| `0x10–0x80` | *Reservados* | Para expansión futura |

---

## 4. Flujo de Trabajo y Multiplexación

### 4.1 Ciclo de vida de una petición

```
Cliente                                Servidor
  │                                       │
  │──── REQUEST (id=1, method="tool") ───→│
  │                                       │ procesa...
  │←─── RESPONSE (id=1, result=...) ─────│
  │                                       │
```

- Cada `REQUEST` lleva un `id` (diccionario ID `0x04`).
- El `RESPONSE` replica el `id` para correlación.
- `NOTIFY` no lleva `id` ni espera respuesta.

### 4.2 Multiplexación (MUX)

El frame `0x09 MUX` envuelve otro frame LUMEN en un canal lógico:

```
MUX Frame:
┌──────────────────────────────────────────────────────────────┐
│ [LEN:Hyb128] [0x09] [FLAGS]                                  │
│ [CHANNEL:1B] [CTRL:4b] [RESERVED:4b]                        │
│ [INNER: LUMEN frame completo]                                │
└──────────────────────────────────────────────────────────────┘

CTRL bits:
  bit0: OPEN  — Crear canal lógico
  bit1: CLOSE — Cerrar canal lógico
  bit2: PAUSE — Backpressure (pausar envío)
  bit3: RESUME — Reanudar envío
```

- **Sin overhead en frames normales**: Solo se paga MUX cuando se usa.
- **256 canales lógicos** sobre una única conexión física.
- **Control de flujo por canal**: Evita head-of-line blocking.

### 4.3 TokenStream — Streaming nativo para LLMs

```
Inicialización:
┌────────────────────────────────────────────┐
│ [0x06] [FLAGS]                             │
│ [STREAM_ID:2B] [TOKEN_TYPE:1B]             │
└────────────────────────────────────────────┘

TOKEN_TYPE:
  0x00 = UTF-8 text tokens
  0x01 = u16 token IDs
  0x02 = u32 token IDs
  0x03 = f32 embeddings (4 bytes)

Ráfagas de datos:
┌────────────────────────────────────────────┐
│ [0x04] [FLAGS]                             │
│ [STREAM_ID:2B] [BURST_LEN:Hyb128] [TOKENS] │
└────────────────────────────────────────────┘

Cierre: BURST_LEN = 0 en STREAM_DATA
```

---

## 5. Compresión Semántica (Diccionarios)

### 5.1 Arquitectura

```
Sin comprimir:  {"tool": "search", "arguments": {"query": "hola"}}
Comprimido:     {0x00: "search", 0x01: {lookup("query"): "hola"}}
```

### 5.2 Diccionario Estático (IDs `0x00–0x7F`)

128 entradas predefinidas. **Nunca cambian.** → Ver [`DICTIONARY.md`](DICTIONARY.md).

### 5.3 Diccionario de Sesión (IDs `0x80–0xFE`)

127 entradas negociadas en handshake y actualizables vía `DICT_SYNC` (`0x07`):

```
DICT_SYNC payload:
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
Cliente: "Mi dict v3, 142 entradas"
Servidor: "Tengo v3 con 140. Envío delta."
          → SCHEMA_PATCH ADD entradas 141, 142
Cliente: "ACK dict v3 completo (142 entradas)"
```

### 5.5 ID 0xFF — Clave sin comprimir

Cuando una clave no está en ningún diccionario, se transmite en texto plano.

---

## 6. Late Binding — Descubrimiento Dinámico

### 6.1 DISCOVER (0x08)

```
DISCOVER Request:  [0x08] [FLAGS] [SCOPE:1B]
SCOPE:
  0x00 = All (tools + resources + prompts + capabilities)
  0x01 = Tools only
  0x02 = Resources only
  0x03 = Capabilities only

DISCOVER Response: [0x02] [FLAGS] [SCOPE:1B] [SCHEMA...]
```

La respuesta puede ser **incremental** (solo lo nuevo desde la última sincronización).

---

## 7. Seguridad Integrada (Zero-Trust)

### 7.1 Handshake

```
Cliente → Servidor:
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

Un nodo puede **restringir más** un Macaroon sin invalidar la firma:

```
Orquestador recibe:    op: filesystem.read:/
Delega a sub-agente:   op: filesystem.read:/home/user/project/src  ← atenuado
Sub-agente NO puede:   ❌ Leer /etc/passwd
```

---

## 8. Tablas de Referencia

### 8.1 Tipos de Frame

| ID | Tipo | Overhead adicional |
|----|------|--------------------|
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
|-----|---------|--------|
| 0 | `0x01` | COMPRESSED |
| 1 | `0x02` | ENCRYPTED |
| 2 | `0x04` | PRIORITY |
| 3 | `0x08` | FRAGMENTED |

---

## 9. Referencias

- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
- [Macaroons: Cookies with Contextual Caveats](https://research.google/pubs/pub41892/)
- [LEB128 Encoding](https://en.wikipedia.org/wiki/LEB128)
- Implementación de referencia: [`implementations/rust/`](implementations/rust/)
- WASM bindings: `wasm-pack build --target web --features wasm` → `pkg/lumen.js`

---

*LUMEN v1.0-draft — Última actualización: 2026-06-14*
