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
├── SPEC.md                  ← especificación completa del protocolo (9 secciones)
├── DICTIONARY.md            ← glosario de 128 IDs estáticos
└── /implementations/
    ├── /rust/               ← implementación de referencia
    │   ├── Cargo.toml
    │   └── src/
    │       ├── lib.rs
    │       ├── hyb128.rs    ← encoding híbrido de longitud
    │       ├── frame.rs     ← parser/builder de frames
    │       ├── dict.rs      ← diccionario O(1) con OnceLock<HashMap>
    │       ├── compress.rs  ← compact binary payload (TAG + dict)
    │       ├── fixtures.rs  ← generadores de datos realistas
    │       ├── transport.rs ← abstracción de transporte
    │       └── bin/
    │           └── shootout.rs ← benchmark LUMEN vs JSON-RPC
    └── /typescript/         ← binding para Node/VS Code (próximamente)
```

---

## 🦀 Implementación Rust

```bash
cd implementations/rust
cargo test    # 38 tests, 0 warnings
cargo run --bin shootout   # benchmark LUMEN vs JSON-RPC
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

### frame + compress

```rust
use lumen::{frame, compress};
use serde_json::json;

let payload = json!({"tool": "search", "arguments": {"query": "hello"}});
let compressed = compress::compress(&payload);  // 30-75% más pequeño
let mut buf = vec![0u8; frame::build_size(compressed.len())];
let n = frame::build(frame::TYPE_REQUEST, frame::FLAG_COMPRESSED, &compressed, &mut buf);

match frame::parse(&buf[..n]) {
    frame::ParseResult::Complete { frame, .. } => {
        let value = compress::decompress(frame.payload).unwrap();
        println!("{}", serde_json::to_string_pretty(&value).unwrap());
    }
    _ => {}
}
```

### dict O(1)

```rust
use lumen::dict;

// Resolve: ID → key (O(1) array lookup)
assert_eq!(dict::resolve(0x00), Some("tool"));

// Lookup: key → ID (O(1) HashMap via OnceLock)
assert_eq!(dict::lookup_fast("tool"), Some(0x00));
assert_eq!(dict::lookup_fast("nonexistent"), None);
```

### Compact binary format

```
Value tags:  0xE0=NULL  0xE1=BOOL  0xE2=FLOAT(f64 LE)  0xE3=INT(LEB128 zigzag)
             0xE4=STR_DICT(1B ID)  0xE5=STR_RAW  0xE6=ARRAY  0xE7=OBJECT

Keys inside objects:  0x00..0x7E = dict ID  0xFF = raw UTF-8
```

---

## 📊 Benchmark — LUMEN vs JSON-RPC

5 escenarios realistas de MCP, medidos con `cargo run --bin shootout`:

```
╔════════════════════════════════════════╤═══════════╤═══════════╤══════════╤═════════╗
║ Scenario                               │ JSON wire │ LUMEN wire│ Ahorro   │ Speedup ║
╠════════════════════════════════════════╪═══════════╪═══════════╪══════════╪═════════╣
║ S1: tools/list (1000 tools)            │ 390.86 KB │ 270.14 KB │  30.9%   │  1.82×  ║
║ S2: file_context (5 MB, 50 archivos)   │  5.01 MB  │  4.89 MB  │   2.5%   │  9.09×  ║
║ S3: token_stream (10K tokens)          │ 732.90 KB │ 184.17 KB │  74.9%   │  4.18×  ║
║ S4: multi_agent (1K reqs, 10 agentes)  │ 109.03 KB │  69.72 KB │  36.1%   │  2.00×  ║
║ S5: heartbeat (100K latidos)           │     89 B  │     48 B  │  46.1%   │  1.68×  ║
╚════════════════════════════════════════╧═══════════╧═══════════╧══════════╧═════════╝
```

**🏆 LUMEN gana en TODOS los escenarios en wire size Y velocidad.**

### Por qué LUMEN es más rápido

| Factor | JSON-RPC | LUMEN |
|---|---|---|
| Overhead mensaje vacío | ~40 bytes | **3 bytes** |
| Overhead mensaje típico | ~60 bytes | **~5 bytes** |
| Formato payload | JSON con escaping | Binary Tags + Dict IDs |
| Keys repetidas | String completo cada vez | **1 byte** (dict ID) |
| Strings largos (>1KB) | Escapa `\"`, `\n`, `\\` | **Raw binary, sin escape** |
| Lookup de diccionario | N/A | **O(1)** `OnceLock<HashMap>` |
| Framing | Delimitadores `\n` | Hyb128 autodelimitado O(1) |
| Streaming LLM | JSON por token (~75 B/token) | **Binary (~18 B/token)** |
| Compresión | No nativa | Diccionario 128+127 IDs |
| Zero-Copy | No | Sí (mmap, LTA Nivel 2) |
| Zero-Trust | No | Macaroons atenuables |
| Late Binding | No | DISCOVER + SchemaPatch |

### Dónde brilla cada escenario

- **S3 (74.9% ahorro):** Cada token LLM pasa de ~75 bytes JSON a ~18 bytes binarios. Hyb128 framing + sin comillas.
- **S2 (9.09× más rápido):** Archivos de 100KB source code — LUMEN escribe los bytes crudos sin escapar `"`, `\n`, `\t`. `serde_json` sufre horrores con esto.
- **S1/S4 (30-36% ahorro):** Keys como `"name"`, `"description"`, `"inputSchema"`, `"method"`, `"params"` colapsan de 10-15 bytes a **1 byte** cada una.
- **S5 (46.1% ahorro):** Un heartbeat LUMEN pesa 48 bytes vs 89 de JSON-RPC. ×1M heartbeats: 45 MB vs 85 MB.

---

## 📝 Licencia

MIT
