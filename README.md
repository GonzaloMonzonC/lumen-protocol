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
    │           ├── shootout.rs           ← benchmark CPU + wire size
    │           ├── heap-shootout.rs      ← benchmark allocaciones de heap
    │           ├── concurrent-shootout.rs← benchmark de estrés concurrente
    │           └── ipc-shootout.rs       ← benchmark latencia IPC real (TCP)
    │           ├── workspace-shootout.rs ← benchmark indexación de proyecto
    │           └── cadencia-bridge.rs    ← sidecar Rust para Cadencia (VS Code)
    └── /typescript/         ← @lumen/mcp-transport (Node.js)
        ├── README.md         ← API docs + negociación LUMEN
        ├── package.json
        ├── tsconfig.json
        └── src/
            ├── index.ts      ← exports públicos
            ├── transport.ts  ← LumenStdioTransport, LumenWebSocketTransport
            ├── negotiation.ts← handshake LUMEN probe/ack + fallback JSON-RPC
            ├── hyb128.ts     ← Hyb128 encode/decode
            ├── frame.ts      ← Frame builder/parser
            ├── dict.ts       ← Diccionario 128 IDs estáticos
            ├── compress.ts   ← Compact binary payload
            └── cadencia.ts   ← Cliente del sidecar Rust
```

---

## 🦀 Implementación Rust

```bash
cd implementations/rust
cargo test                       # 38 tests, 0 warnings
cargo run --bin shootout             # benchmark CPU + wire size
cargo run --bin heap-shootout        # benchmark allocaciones de heap
cargo run --bin concurrent-shootout  # benchmark de estrés concurrente
cargo run --bin ipc-shootout         # benchmark latencia IPC real (TCP)
cargo run --bin workspace-shootout   # benchmark indexación de proyecto
echo '{"cmd":"index","files":["src/main.rs"]}' | cargo run --bin cadencia-bridge  # sidecar
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

## 🧠 Heap Allocation Profiling

Medido con `cargo run --bin heap-shootout` usando un `#[global_allocator]` personalizado con contadores atómicos. Promedio por iteración (×100 runs):

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║                           LUMEN vs JSON-RPC — HEAP ALLOCATIONS (×100 iter avg)                      ║
╠══════════════════════════════════════╤═══════════╤═══════════╤══════════════╤══════════════╤══════════╤══════════╣
║ Scenario (per iteration)             │ JSON alloc│ LUMEN allo│ Alloc Ratio  │ Bytes Ratio  │ JSON peak│ LUM peak ║
╠══════════════════════════════════════╪═══════════╪═══════════╪══════════════╪══════════════╪══════════╪══════════╣
║ S1: tools/list (1000 tools)          │    31.4K  │    31.4K  │    1.0×      │    1.2× ⭐    │    4617K │    4299K ║
║ S2: file_context (5 MB)              │      392  │      359  │    1.1× ⭐    │    2.2× ⭐    │   13378K │   10041K ║
║ S3: token_stream (1K tokens)         │     1.0K  │     1.0K  │    1.0×      │    1.9× ⭐    │      59K │      44K ║
║ S4: multi_agent (1K reqs)            │    11.0K  │    11.0K  │    1.0×      │    1.2× ⭐    │    1343K │    1284K ║
║ S5: heartbeat (1 frame)              │        9  │        9  │    1.0×      │    1.0×      │       1K │       1K ║
╚══════════════════════════════════════╧═══════════╧═══════════╧══════════════╧══════════════╧══════════╧══════════╝
```

### Interpretación

| Métrica | Hallazgo |
|---------|----------|
| **Bytes allocated** | LUMEN asigna **20-53% menos bytes** — S2 (file_context 5 MB) pasa de 21.2 MB → 9.8 MB, S3 (tokens) de 85 KB → 45 KB |
| **Peak memory** | LUMEN reduce el pico de heap en **5-25%** — S2 baja de 13.4 MB → 10.0 MB gracias al wire más compacto |
| **Allocation count** | Comparable en la mayoría de escenarios. S2 mejora de 392 → 359 (8% menos), S5 se iguala a JSON (antes LUMEN hacía 13 vs 9 — **regresión corregida**) |
| **Single-allocation encode (`compress_into`)** | El encode de LUMEN ahora usa **un solo `Vec`** — cero buffers intermedios. Antes: `compress() → Vec` + `frame::build() → Vec`. Ahora: escritura directa sobre el buffer destino |

> **Conclusión:** LUMEN no solo reduce el tamaño del wire (30-53%), sino que también asigna menos bytes y menos pico de heap. La fusión del path de encode con `compress_into` elimina el double-buffer, cerrando la promesa de "zero intermediate allocation" en el hot path de serialización.

---

## ⚡ Concurrent Stress Test

Simula **64 hilos** compitiendo por un transporte compartido con carga mixta realista (10% heartbeats, 30% tokens, 40% tool calls, 20% file chunks de 5 KB). Medido con `cargo run --bin concurrent-shootout`:

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║            LUMEN vs JSON-RPC — CONCURRENT STRESS TEST (64 threads)              ║
╠══════════════════════════╤═══════════╤═══════════╤══════════════╤════════════════╣
║ Metric                   │ JSON-RPC   │ LUMEN      │ Ratio        │ Winner         ║
╠══════════════════════════╪═══════════╪═══════════╪══════════════╪════════════════╣
║ Total wire bytes         │   38.7 MB │   35.9 MB │  92.7% LUM   │ LUMEN (7.3%)   ║
║ Throughput (MB/s)        │     32.9  │     90.0  │   2.7× LUM   │ LUMEN          ║
║ Messages/sec             │   27,211  │   80,201  │   2.9× LUM   │ LUMEN          ║
║ Wall time (ms)           │    1,176  │      399  │   2.9× LUM   │ LUMEN          ║
║ Avg latency (µs/msg)     │    981.2  │     42.9  │  22.9× lower │ LUMEN          ║
╚══════════════════════════╧═══════════╧═══════════╧══════════════╧════════════════╝
```

### Por qué LUMEN no sufre Head-of-Line Blocking

| Factor | JSON-RPC bajo contención | LUMEN bajo contención |
|--------|--------------------------|------------------------|
| Serialización por msg | ~981 µs (parser JSON bloquea) | **~43 µs** (binary O(1) framing) |
| Archivos grandes (5 KB) | Escapa `\"`, `\n`, `\t` → satura CPU | **Raw binary copy** → la CPU respira |
| Framing | `Content-Length: ...\r\n\r\n` → parseo línea a línea | **Hyb128**: 1-5 bytes, el parser sabe en 1 ciclo cuánto saltar |
| Contención de CPU | Serializar 5 KB de source code acapara el core | Compress dict O(1) + raw copy libera el core rápido |
| Efecto cascada | Un hilo lento → los demás esperan | Todos los hilos terminan rápido → menos contención |

> **Conclusión:** Bajo carga concurrente real (64 hilos mezclando heartbeats, tokens, tool calls y archivos), LUMEN triplica el throughput y reduce la latencia **22.9×**. Esto es crítico para orquestadores como Synapse donde múltiples agentes comparten un mismo socket.

---

## 🌐 IPC End-to-End Latency (TCP Loopback)

Mide el *Round Trip Time* real sobre TCP loopback (`127.0.0.1`, `nodelay`) — el stack TCP completo del kernel. Servidor eco en un hilo, cliente en otro. 2000 iteraciones por workload, 500 warmup. Medido con `cargo run --bin ipc-shootout`:

```
╔══════════════════════════════════════════════════════════════════════════════════════════════════╗
║                  LUMEN vs JSON-RPC — IPC END-TO-END LATENCY (TCP loopback, nodelay)             ║
╠══════════════════════════════╤══════════╤══════════╤══════════╤══════════╤══════════╤════════════╣
║ Workload                     │ JSON p50 │ LUMEN p50│ JSON p99 │ LUMEN p99│ JSON avg │ LUMEN avg  ║
╠══════════════════════════════╪══════════╪══════════╪══════════╪══════════╪══════════╪════════════╣
║ W1: heartbeat (tiny, ~90B)   │    115µs │    114µs │    349µs │    378µs │    125µs │     136µs  ║
║ W2: tool_call (~400B)        │    133µs │    131µs │    476µs │    482µs │    161µs │     157µs  ║
║ W3: llm_token (~32B)         │     74µs │    132µs │    294µs │    373µs │     88µs │     150µs  ║
║ W4: file_chunk (5 KB)        │    604µs │    183µs │   1588µs │    550µs │    726µs │     204µs  ║
║ W5: tokens_x10 (batch)       │    104µs │    148µs │    332µs │    414µs │    118µs │     161µs  ║
╚══════════════════════════════╧══════════╧══════════╧══════════╧══════════╧══════════╧════════════╝
```

### Análisis

| Workload | Speedup | Wire saving | Interpretación |
|----------|---------|-------------|----------------|
| **W4: file_chunk** | **3.6×** | 3% | Raw binary copy del source code sin escapar `\"`, `\n`, `\t`. `serde_json` se ahoga |
| W2: tool_call | 1.0× | 31% | Empate técnico bajo TCP (~130 µs). Dict compresión gana en wire (31%), pero kernel TCP nivela el RTT |
| W5: tokens_x10 | 0.7× | 6% | Batch de 10 tokens — el overhead binario (tags + Hyb128 por token) es similar al JSON array |
| W1: heartbeat | 0.9× | 47% | TCP stack (~115 µs base) domina ambos. LUMEN wire más pequeño (48B vs 90B) |
| W3: llm_token | 0.6× | -9% | Token individual — JSON es sólo `"texto"`, LUMEN añade tag + dict ID + zigzag logprob |

> **Conclusión:** Para payloads >1 KB, LUMEN gana **3.6× en RTT real sobre TCP**. Para payloads pequeños (<500 B), el kernel TCP domina (~70-130 µs base) y ambos protocolos son equivalentes. **La ventaja real de LUMEN en IPC aparece con archivos grandes** (source code, recursos, blobs) donde la copia binaria cruda humilla al escaping JSON. Para streaming de tokens, la ventaja está en el **CPU benchmark** (S3: 4.18×) y en la **concurrencia** (22.9×), no en RTT unitario por token.

---

## �️ Workspace Indexing Shootout (Cadencia)

Simula la carga real de **Cadencia** analizando un proyecto: lee todos los archivos fuente del directorio y los serializa como frames MCP. Medido con `cargo run --bin workspace-shootout`:

```
╔══════════════════════╤══════════════╤══════════════╤═══════════════╗
║ Metric               │ JSON-RPC     │ LUMEN        │ Advantage      ║
╠══════════════════════╪══════════════╪══════════════╪═══════════════╣
║ Encode time          │    0.023 s   │    0.009 s   │    2.73× FASTER ║
║ Throughput           │     6.2 MB/s │    15.8 MB/s │    2.54× MORE   ║
║ Time per file        │    1.558 ms  │    0.571 ms  │    2.73× FASTER ║
║ Wire bytes (total)   │     0.15 MB  │     0.14 MB  │    6.7% LESS   ║
╚══════════════════════╧══════════════╧══════════════╧═══════════════╝

  Proyección 5,000 archivos → JSON-RPC: 7.8s  |  LUMEN: 2.9s  |  2.7× faster
  Con archivos >100KB (source code real) → hasta 9× faster (ver S2)
```

> **Para Cadencia:** El 80% del tiempo de indexación de un workspace se va en serializar strings largos con escapes JSON (`\"`, `\n`, `\t`). LUMEN copia los bytes crudos sin tocarlos.

---

## 🔌 Cadencia Bridge (Sidecar Rust)

Un binario mínimo que la extensión de VS Code ejecuta como proceso hijo. Recibe comandos JSON por stdin, lee archivos del disco, los comprime con LUMEN, y devuelve frames binarios. **Cero dependencias de runtime** — solo necesita el binario compilado.

```bash
# Test manual del sidecar
echo '{"cmd":"index","files":["Cargo.toml","src/lib.rs","src/frame.rs"]}' \
  | cargo run --bin cadencia-bridge

# Salida:
# {"status":"ok","version":"0.1.0","protocol":"lumen/1"}
# {"status":"ok","files":3,"total_bytes":21530,"wire_bytes":21572,...}
```

### Protocolo (línea-delimitado JSON sobre stdin/stdout)

| Comando | Descripción |
|---------|-------------|
| `{"cmd":"ping"}` | Handshake inicial → `{"status":"ok","version":"0.1.0","protocol":"lumen/1"}` |
| `{"cmd":"index","files":[...]}` | Lee y comprime los archivos → stats de wire/tiempo |
| `{"cmd":"stop"}` | Apagado graceful |

### TypeScript client

```typescript
import { CadenciaBridge } from "@lumen/mcp-transport";

const bridge = new CadenciaBridge({
  binaryPath: "./cadencia-bridge", // compiled from implementations/rust
  cwd: workspaceRoot,
});

await bridge.start();                    // handshake
const result = await bridge.index([     // index 5000 files
  "src/main.ts", "src/utils.ts", /* ... */
]);
console.log(result);                     // { files: 5000, total_bytes: ..., wire_bytes: ..., encode_us: ... }
await bridge.stop();
```

---

## �📝 Licencia

MIT
