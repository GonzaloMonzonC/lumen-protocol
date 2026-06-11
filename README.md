# LUMEN — Lightweight Universal Model Exchange Network

Un protocolo binario de alta eficiencia para la comunicación entre sistemas MCP (Model Context Protocol). Diseñado desde cero para superar las limitaciones de JSON-RPC con compresión nativa, zero-copy, zero-trust y streaming optimizado para LLMs.

---

## 🎯 Motivación

JSON-RPC, el protocolo actual de MCP, es verboso, lento de parsear y no está optimizado para:
- **Streaming de tokens** de LLMs en tiempo real
- **Alto throughput** en comunicación local (stdio/UDS)
- **Zero-copy** sobre memoria compartida
- **Zero-trust** con permisos granulares atenuables

**LUMEN** resuelve todo esto con un protocolo binario autodelimitado de ~4 bytes de overhead.

---

## 🧬 Anatomía del protocolo

```
┌──────────────────────────────────────────────────────┐
│ [LEN:Hyb128] [TYPE:1B] [FLAGS:1B] [PAYLOAD:LEN]     │
└──────────────────────────────────────────────────────┘
```

### Hyb128 — Longitud híbrida O(1)

| Mode | Bits | Rango | Bytes totales |
|------|------|-------|---------------|
| `00` | `00` | 0–63 B | **1 byte** |
| `10` | `10` | 64 B–64 KB | 3 bytes |
| `11` | `11` | 64 KB–4 GB | 5 bytes |
| `01` | `01` | >4 GB (raro) | LEB128 |

→ El parser sabe en **1 sola lectura de CPU** cuántos bytes saltar. Sin loops, sin branch misprediction.

### Tipos de frame

| ID | Tipo | Descripción |
|----|------|-------------|
| `0x01` | `REQUEST` | Petición cliente → servidor |
| `0x02` | `RESPONSE` | Respuesta servidor → cliente |
| `0x03` | `NOTIFY` | Fire-and-forget |
| `0x04` | `STREAM_DATA` | Datos de streaming |
| `0x05` | `SCHEMA_PATCH` | Delta de esquema en caliente |
| `0x06` | `STREAM_INIT` | Inicializar stream de tokens |
| `0x07` | `DICT_SYNC` | Sincronización de diccionario |
| `0x08` | `DISCOVER` | Introspección dinámica (late binding) |
| `0x09` | `MUX` | Multiplexación de canales lógicos |
| `0x0A` | `HEARTBEAT` | Keep-alive |

---

## 🔤 Diccionario de compresión

128 entradas estáticas (IDs `0x00–0x7F`) + 127 entradas dinámicas por sesión (`0x80–0xFE`).

Las claves más frecuentes se mapean a 1 byte:

| ID | Clave | ID | Clave |
|----|-------|----|-------|
| `0x00` | `tool` | `0x08` | `text` |
| `0x01` | `arguments` | `0x20` | `resources` |
| `0x02` | `result` | `0x21` | `tools` |
| `0x03` | `error` | `0x4F` | `usage` |

`0xFF` = clave sin comprimir (escape hatch).

---

## 🔐 Zero-Trust con Macaroons

Cada handshake intercambia **Capability Tokens** (Macaroons) con caveats como:
```
op: filesystem.read:/home/user/project
op: tool.call:search_code
exp: 2026-06-11T18:00:00Z
rate: 100/min
```

Los nodos intermedios **atenúan** los permisos (añaden restricciones, nunca las quitan) antes de delegar a sub-agentes.

---

## 🌊 Streaming nativo

**TokenStream** optimizado para LLMs:

```
Init:  [0x06] [STREAM_ID:2B] [TOKEN_TYPE:1B]
Data:  [0x04] [STREAM_ID:2B] [BURST_LEN:Hyb128] [TOKENS...]
Close: BURST_LEN = 0
```

Sin terminadores frágiles. Sin re-serializar cabeceras. Ráfagas delimitadas.

---

## 🚚 Transporte (LTA)

LUMEN es agnóstico al transporte, con 3 niveles:

| Nivel | Nombre | Transportes |
|-------|--------|-------------|
| 1 | Stream | stdio, TCP, UDS, WebSocket |
| 2 | Zero-Copy | UDS + mmap |
| 3 | Datagram | UDP, multicast (experimental) |

Los frames son autodelimitados (Hyb128) → funcionan sobre cualquier stream confiable sin capas extra.

---

## 🏗️ Estructura del proyecto

```
/LUMEN/
├── README.md               ← este archivo
├── SPEC.md                  ← especificación completa (próximamente)
├── DICTIONARY.md            ← glosario de IDs estáticos
└── /implementations/
    ├── /rust/               ← implementación de referencia
    │   ├── Cargo.toml
    │   └── src/
    │       ├── lib.rs
    │       ├── hyb128.rs    ← encoding híbrido de longitud
    │       ├── frame.rs     ← parser/builder de frames
    │       ├── dict.rs      ← diccionario de compresión
    │       └── transport.rs ← abstracción de transporte
    └── /typescript/         ← binding para Node/VS Code (próximamente)
```

---

## 🦀 Implementación Rust

```bash
cd implementations/rust
cargo test    # hyb128 + frame + dict
cargo build   # compilación de la librería
```

### hyb128

```rust
use lumen::hyb128;

let mut buf = [0u8; hyb128::MAX_ENCODED_LEN];
let n = hyb128::encode(42, &mut buf);
let decoded = hyb128::decode(&buf[..n]).unwrap();
assert_eq!(decoded.value, 42);
assert_eq!(n, 1); // solo 1 byte para valores ≤ 63
```

### frame

```rust
use lumen::frame;

let payload = b"{\"method\":\"tools/list\"}";
let mut buf = vec![0u8; frame::build_size(payload.len())];
let n = frame::build(frame::TYPE_REQUEST, frame::FLAG_PRIORITY, payload, &mut buf);

match frame::parse(&buf[..n]) {
    frame::ParseResult::Complete { frame, .. } => {
        println!("Type: {}", frame.type_name());
    }
    _ => {}
}
```

---

## 📊 Comparativa

| | JSON-RPC (MCP) | LUMEN |
|---|---|---|
| Overhead mensaje vacío | ~40 bytes | **3 bytes** |
| Overhead mensaje típico | ~60 bytes | ~4 bytes |
| Formato | Texto (JSON) | Binario |
| Framing | Delimitadores `\n` | Hyb128 autodelimitado |
| Compresión | No nativa | Diccionario 1-byte IDs |
| Streaming LLM | No nativo | TokenStream dedicado |
| Zero-Copy | No | Sí (mmap) |
| Zero-Trust | No | Macaroons atenuables |
| Late Binding | No | DISCOVER + SchemaPatch |
| Tamaño máximo payload | Ilimitado | Ilimitado (Hyb128 escala a 4 GB+) |

---

## 📝 Licencia

MIT
