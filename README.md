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

> 💡 Combina Macaroons con **Wire Encryption (§7.4 del SPEC)** para confidencialidad +
> autenticación mutua completa.

### 🔒 Wire Encryption (ChaCha20-Poly1305 + X25519)

Cifrado autenticado opcional a nivel de frame, negociado durante el handshake:

```
Frame cifrado:
┌──────────────────────────────────────────────────────────────┐
│ [Hyb128] [TYPE:1B] [FLAGS:1B | 0x02] [NONCE:12B] [CIPHER+TAG]│
└──────────────────────────────────────────────────────────────┘
                          overhead: 28 bytes
```

| Mecanismo | Algoritmo |
|---|---|
| Cifrado | ChaCha20 (256-bit key) |
| Integridad | Poly1305 MAC |
| Key exchange | X25519 (efímero por sesión) |
| Anti-replay | Nonce counter monótono por dirección |
| Negociación | PROBE/PROBE_ACK con clave pública base64 |

```rust
// Rust (lumen crate)
let kp = Keypair::generate();
let mut cipher = Cipher::new(&kp.derive_shared_secret(&peer_pk));
let frame = cipher.build_encrypted_frame(TYPE_REQUEST, 0, b"payload")?;
let plaintext = cipher.decrypt(encrypted_payload)?;
```

```typescript
// TypeScript (Web Crypto API)
const kp = await generateKeypair();
const shared = await deriveSharedSecret(kp.secretKey, peerPublicKey);
const cipher = new Cipher(); await cipher.init(shared);
const frame = await cipher.buildEncryptedFrame(TYPE_REQUEST, 0, payload);
const plaintext = await cipher.decrypt(encryptedPayload);
```

| Lenguaje | Estado |
|---|---|
| **Rust** | ✅ `crypto.rs` — 8 tests |
| **TypeScript** | ✅ `crypto.ts` — WebCrypto |
| Python, C#, PHP | *(pendiente)* |

> ⚠️ Sin PKI en esta versión. Para autenticación de identidad, usar Macaroons (§7.2 SPEC).

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
| 2 | Zero-Copy | UDS + mmap (Unix), Named SHM (Windows) ✅ |
| 3 | Datagram | UDP, multicast ✅ |

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
    │       ├── dict.rs      ← diccionario O(1): 128 estáticas + 127 sesión (OnceLock<RwLock<>>)
    │       ├── compress.rs  ← compact binary payload (TAG + dict)
    │       ├── ffi.rs       ← C FFI exports (gated out for WASM builds)
    │       ├── wasm.rs      ← WASM bindings (wasm-bindgen, builds with wasm-pack)
    │       ├── fixtures.rs  ← generadores de datos realistas
    │       ├── transport.rs ← abstracción de transporte
    │       ├── crypto.rs    ← ChaCha20-Poly1305 + X25519 wire encryption
    │       ├── handshake.rs ← Transport + encryption negotiation
    │       └── bin/
    │           ├── shootout.rs           ← benchmark CPU + wire size
    │           ├── heap-shootout.rs      ← benchmark allocaciones de heap
    │           ├── concurrent-shootout.rs← benchmark de estrés concurrente
    │           ├── ipc-shootout.rs       ← benchmark latencia IPC real (TCP)
    │           ├── shm-shootout.rs       ← benchmark zero-copy shared memory
    │           ├── workspace-shootout.rs ← benchmark indexación de proyecto
    │           ├── dgram-shootout.rs     ← benchmark UDP roundtrip (Nivel 3)
    │           └── cadencia-bridge.rs    ← sidecar Rust para Cadencia (VS Code)
    ├── /typescript/         ← @lumen/mcp-transport (Node.js)
    │   ├── README.md         ← API docs + negociación LUMEN
    │   ├── package.json
    │   ├── tsconfig.json
    │   └── src/
    │       ├── index.ts      ← exports públicos
    │       ├── transport.ts  ← LumenStdioTransport, LumenWebSocketTransport
    │       ├── negotiation.ts← handshake LUMEN probe/ack + fallback JSON-RPC
    │       ├── hyb128.ts     ← Hyb128 encode/decode
    │       ├── frame.ts      ← Frame builder/parser
    │       ├── frame-assembler.ts ← Zero-allocation streaming reassembler
    │       ├── dict.ts       ← Diccionario 128 estáticas + 127 sesión
    │       ├── compress.ts   ← Compact binary payload
    │       ├── compress_ffi.ts← FFI wrapper (Rust → Node via koffi)
    │       ├── shm_ffi.ts    ← SHM zero-copy transporte (Nivel 2, FFI)
    │       ├── dgram.ts      ← Datagram UDP/multicast (Nivel 3)
    │       ├── zeroalloc.ts  ← ZeroAllocDecompressor (54% menos GC)
    │       └── cadencia.ts   ← Cliente del sidecar Rust
    ├── /python/             ← lumen-py (pip install)
    │   ├── README.md
    │   ├── pyproject.toml
    │   ├── bench.py         ← benchmark suite
    │   ├── tests/
    │   │   └── test_lumen.py ← 94 tests
    │   └── src/lumen/
    │       ├── __init__.py
    │       ├── hyb128.py    ← Hyb128 encode/decode
    │       ├── frame.py     ← Frame builder/parser
    │       ├── frame_assembler.py ← Streaming frame reassembler
    │       ├── dict.py      ← Diccionario 128 estáticas + 127 sesión
    │       ├── compress.py  ← Compact binary payload
    │       ├── negotiation.py ← Probe/ack handshake
    │       ├── transport.py ← LumenStdioTransport + LumenWebSocketTransport
    │       └── cadencia.py  ← Rust sidecar bridge client
    ├── /csharp/              ← lumen-cs (.NET 9)
    │   ├── LumenCSharp.csproj
    │   ├── Dict.cs          ← Diccionario 128 estáticas + 127 sesión
    │   ├── Hyb128.cs        ← Hyb128 encode/decode
    │   ├── LumenCompress.cs ← Compact binary payload (native C#)
    │   ├── LumenFFI.cs      ← P/Invoke FFI (Rust → .NET)
    │   └── Program.cs       ← Test harness + benchmarks
    └── /php/                ← lumen-php (composer)
        ├── composer.json
        ├── bench.php        ← benchmark suite (8 categorías, 74 resultados)
        ├── tests/
        │   └── e2e_test.php ← cross-implementation e2e (217 tests)
        └── src/
            ├── Compress.php       ← compact binary payload
            ├── Dict.php           ← diccionario 128 estáticas + 127 sesión
            ├── Hyb128.php         ← Hyb128 encode/decode
            ├── Frame.php          ← frame parser
            └── FrameAssembler.php ← streaming frame assembler
```

---

## 🦀 Implementación Rust

```bash
cd implementations/rust
cargo test                       # 62 tests, 0 warnings
cargo run --bin shootout             # benchmark CPU + wire size
cargo run --bin heap-shootout        # benchmark allocaciones de heap
cargo run --bin concurrent-shootout  # benchmark de estrés concurrente
cargo run --bin ipc-shootout         # benchmark latencia IPC real (TCP)
cargo run --bin shm-shootout         # benchmark zero-copy shared memory
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

// Resolve: ID → key (static 0x00–0x7F, session 0x80–0xFE)
assert_eq!(dict::resolve(0x00), Some("tool"));
assert_eq!(dict::resolve_any(0x80), None); // session slot still empty

// Lookup: key → ID (static dict first, then session dict)
assert_eq!(dict::lookup_fast("tool"), Some(0x00));
assert_eq!(dict::lookup_fast("nonexistent"), None);

// Session dictionary (127 dynamic slots)
dict::register_session("my_custom_key", 0x80).unwrap();
assert_eq!(dict::resolve_any(0x80), Some("my_custom_key".to_string()));
assert_eq!(dict::lookup_fast("my_custom_key"), Some(0x80));
```

### Compact binary format

```
Value tags:  0xE0=NULL  0xE1=BOOL  0xE2=FLOAT(f64 LE)  0xE3=INT(LEB128 zigzag)
             0xE4=STR_DICT(1B ID)  0xE5=STR_RAW  0xE6=ARRAY  0xE7=OBJECT

Keys inside objects:  0x00..0x7E = dict ID  0xFF = raw UTF-8
```

### WASM (WebAssembly)

Compila el crate Rust a WASM para uso directo desde JavaScript/TypeScript en navegador o edge:

```bash
rustup target add wasm32-unknown-unknown
npm install -g wasm-pack        # o: cargo install wasm-pack
wasm-pack build --target web --features wasm
```

```javascript
import init, { lumen_compress, lumen_decompress, lumen_version } from "./pkg/lumen.js";

await init();

const json = JSON.stringify({ tool: "search", arguments: { query: "hello" } });
const compressed = lumen_compress(json);   // Uint8Array
const restored = lumen_decompress(compressed); // string (JSON)
console.log(lumen_version());              // "0.1.0"
```

El módulo `ffi.rs` (C FFI) se excluye automáticamente del build WASM para evitar
colisión de símbolos (`#[cfg(not(feature = "wasm"))]`).

---

## 📊 Benchmark — LUMEN vs JSON-RPC

6 escenarios realistas de MCP, medidos con `cargo run --bin shootout` (WARMUP=20, MEASURE=200):

```
╔════════════════════════════════════════╤═══════════╤═══════════╤══════════╤═════════╗
║ Scenario                               │ JSON wire │ LUMEN wire│ Ahorro   │ Speedup ║
╠════════════════════════════════════════╪═══════════╪═══════════╪══════════╪═════════╣
║ S1: tools/list (1000 tools)            │ 390.86 KB │ 267.41 KB │  31.6%   │  2.06×  ║
║ S2: file_context (5 MB, 50 archivos)   │  5.01 MB  │  4.89 MB  │   2.5%   │  7.02×  ║
║ S3: token_stream (10K tokens)          │ 732.90 KB │ 125.57 KB │  82.9%   │  3.00×  ║
║ S4: multi_agent (1K reqs, 10 agentes)  │ 109.03 KB │  67.38 KB │  38.2%   │  1.23×  ║
║ S5: heartbeat (100K latidos)           │     89 B  │     48 B  │  46.1%   │  1.61×  ║
║ S6: session_dict (127 keys)            │  2.50 KB  │    453 B  │  82.3%   │  1.73×  ║
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
| Streaming LLM | JSON por token (~75 B/token) | **Binary (~12 B/token)** |
| Compresión | No nativa | Diccionario 128+127 IDs |
| Zero-Copy | No | **Sí (mmap/shared memory, Nivel 2 ✅)** |
| Zero-Trust | No | Macaroons atenuables |
| Late Binding | No | DISCOVER + SchemaPatch |

### Dónde brilla cada escenario

- **S3 (82.9% ahorro):** Cada token LLM pasa de ~75 bytes JSON a ~12 bytes binarios. Hyb128 framing + sin comillas. El ahorro más extremo del benchmark.
- **S6 (82.3% ahorro):** 127 claves de sesión registradas dinámicamente (0x80–0xFE). Cada clave colapsa de strings de 14 chars a 1 byte. Ideal para dominios especializados.
- **S2 (7.02× más rápido):** Archivos de 100KB source code — LUMEN escribe los bytes crudos sin escapar `"`, `\n`, `\t`. `serde_json` sufre horrores con esto.
- **S1/S4 (31-38% ahorro):** Keys como `"name"`, `"description"`, `"inputSchema"`, `"method"`, `"params"` colapsan de 10-15 bytes a **1 byte** cada una.
- **S5 (46.1% ahorro):** Un heartbeat LUMEN pesa 48 bytes vs 89 de JSON-RPC. ×1M heartbeats: 45 MB vs 85 MB.

---

## 🧠 Heap Allocation Profiling

Medido con `cargo run --bin heap-shootout` usando un `#[global_allocator]` personalizado con contadores atómicos. Promedio por iteración (×100 runs):

```

╔══════════════════════════════════════╤═══════════╤═══════════╤══════════════╤══════════════╤══════════╤══════════╗
║ Scenario (per iteration)             │ JSON alloc│ LUMEN allo│ Alloc Ratio  │ Bytes Ratio  │ JSON peak│ LUM peak ║
╠══════════════════════════════════════╪═══════════╪═══════════╪══════════════╪══════════════╪══════════╪══════════╣
║ S1: tools/list (1000 tools)          │    37.5K  │    37.3K  │    1.0×      │    1.6× ⭐    │    3313K │    2529K ║
║ S2: file_context (5 MB)              │      444  │      411  │    1.1× ⭐    │    2.2× ⭐    │   13366K │   10029K ║
║ S3: token_stream (1K tokens)         │     1.0K  │     1.0K  │    1.0×      │    2.0× ⭐    │     119K │      83K ║
║ S4: multi_agent (1K reqs)            │    14.8K  │    12.8K  │    1.2× ⭐    │    2.0× ⭐    │    1353K │     945K ║
║ S5: heartbeat (1 frame)              │       11  │       11  │    1.0×      │    1.4× ⭐    │       1K │       1K ║
╚══════════════════════════════════════╧═══════════╧═══════════╧══════════════╧══════════════╧══════════╧══════════╝
```

### Interpretación

| Métrica | Hallazgo |
|---------|----------|
| **Bytes allocated** | LUMEN asigna **40-55% menos bytes** — S2 (file_context 5 MB) pasa de 21.2 MB → 9.8 MB, S3 (tokens) de 165 KB → 83 KB |
| **Peak memory** | LUMEN reduce el pico de heap en **24-30%** — S2 baja de 13.4 MB → 10.0 MB, S4 de 1.35 MB → 0.94 MB |
| **Allocation count** | Comparable en la mayoría de escenarios. S4 mejora de 14.8K → 12.8K (14% menos). La fusión `compress_into` elimina el double-buffer |
| **Single-allocation encode** | El encode de LUMEN usa **un solo `Vec`** — cero buffers intermedios. Escritura directa sobre el buffer destino |

> **Conclusión:** LUMEN no solo reduce el tamaño del wire (31-83%), sino que también asigna **40-55% menos bytes** y reduce el pico de heap en **24-30%**. La fusión del path de encode con `compress_into` elimina el double-buffer.

---

## ⚡ Concurrent Stress Test

Simula **64 hilos** compitiendo por un transporte compartido con carga mixta realista (10% heartbeats, 30% tokens, 40% tool calls, 20% file chunks de 5 KB). Medido con `cargo run --bin concurrent-shootout`:

```
╔══════════════════════════╤═══════════╤═══════════╤══════════════╤════════════════╗
║ Metric                   │ JSON-RPC   │ LUMEN      │ Ratio        │ Winner         ║
╠══════════════════════════╪═══════════╪═══════════╪══════════════╪════════════════╣
║ Total wire bytes         │   38.7 MB  │   35.7 MB  │  92.2% LUM   │ LUMEN (7.8%)   ║
║ Throughput (MB/s)        │     29.1   │     50.3   │   1.7× LUM   │ LUMEN          ║
║ Messages/sec             │   24,042   │   45,070   │   1.9× LUM   │ LUMEN          ║
║ Wall time (ms)           │    1,331   │      710   │   1.9× LUM   │ LUMEN          ║
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

> **Conclusión:** Bajo carga concurrente real (64 hilos mezclando heartbeats, tokens, tool calls y archivos), LUMEN duplica el throughput y reduce el wall time 1.9×. Esto es crítico para orquestadores como Synapse donde múltiples agentes comparten un mismo socket.

---

## 🌐 IPC End-to-End Latency (TCP Loopback)

Mide el *Round Trip Time* real sobre TCP loopback (`127.0.0.1`, `nodelay`) — el stack TCP completo del kernel. Servidor eco en un hilo, cliente en otro. 2000 iteraciones por workload, 500 warmup. Medido con `cargo run --bin ipc-shootout`:

```
╔══════════════════════════════╤══════════╤══════════╤══════════╤══════════╤══════════╤══════════╗
║ Workload                     │ JSON p50 │ LUMEN p50│ JSON p99 │ LUMEN p99│ JSON avg │ LUMEN avg║
╠══════════════════════════════╪══════════╪══════════╪══════════╪══════════╪══════════╪══════════╣
║ W1: heartbeat (tiny, ~90B)   │     91µs │    155µs │    297µs │    656µs │    108µs │    173µs ║
║ W2: tool_call (~400B)        │    153µs │    140µs │    571µs │    543µs │    181µs │    177µs ║
║ W3: llm_token (~32B)         │     76µs │    100µs │    222µs │    207µs │     89µs │    111µs ║
║ W4: file_chunk (5 KB)        │    634µs │    161µs │   1199µs │    367µs │    715µs │    177µs ║
║ W5: tokens_x10 (batch)       │     92µs │    108µs │    195µs │    247µs │    102µs │    126µs ║
╚══════════════════════════════╧══════════╧══════════╧══════════╧══════════╧══════════╧══════════╝
```

### Análisis

| Workload | Speedup | Wire saving | Interpretación |
|----------|---------|-------------|----------------|
| **W4: file_chunk** | **4.0×** | 3% | Raw binary copy del source code sin escapar `\"`, `\n`, `\t`. `serde_json` se ahoga |
| W2: tool_call | 1.0× | 33% | Empate técnico bajo TCP (~140-180 µs). Dict compresión gana en wire (33%), pero kernel TCP nivela el RTT |
| W5: tokens_x10 | 0.8× | 6% | Batch de 10 tokens — el overhead binario (tags + Hyb128 por token) es similar al JSON array |
| W1: heartbeat | 0.6× | 47% | TCP stack (~90-150 µs base) domina ambos. LUMEN wire más pequeño (48B vs 90B) pero el kernel manda |
| W3: llm_token | 0.8× | 9% | Token individual — JSON es sólo `"texto"`, LUMEN añade tag + dict ID + zigzag logprob |

> **Conclusión:** Para payloads >1 KB, LUMEN gana **4.0× en RTT real sobre TCP**. Para payloads pequeños (<500 B), el kernel TCP domina (~70-150 µs base) y ambos protocolos son equivalentes. **La ventaja real de LUMEN en IPC aparece con archivos grandes** (source code, recursos, blobs) donde la copia binaria cruda humilla al escaping JSON. Para streaming de tokens, la ventaja está en el **CPU benchmark** (S3: 3.00×) y en la **concurrencia** (1.9×), no en RTT unitario por token.

---

## 🌊 Nivel 3 — Datagram (UDP / Multicast)

El Nivel 3 de LUMEN es **message-oriented**: cada datagrama UDP transporta exactamente un frame LUMEN completo. Sin capa de framing adicional — la frontera del datagrama **es** la frontera del frame. El socket opera en modo no bloqueante con buffer de 65 KB pre-asignado.

```
┌──────────────────────────────────────────────────┐
│  Datagrama UDP                                   │
│  ┌────────────────────────────────────────────┐  │
│  │ [Hyb128:LEN] [TYPE:1B] [FLAGS:1B] [DATA]   │  │
│  └────────────────────────────────────────────┘  │
│  1 datagrama = 1 frame LUMEN                     │
└──────────────────────────────────────────────────┘
```

### ¿Por qué UDP para MCP?

TCP es ideal para streams confiables (Level 1/2), pero hay cargas de trabajo donde **la latencia y el throughput importan más que la entrega garantizada**:

| Carga | TCP (Nivel 1) | UDP (Nivel 3) |
|---|---|---|
| **Service Discovery** | Necesitas conocer IP:puerto de antemano | Una trama multicast DISCOVER llega a todos los agentes del subnet |
| **Telemetría / métricas** | 3-way handshake por conexión → latencia | Fire-and-forget: el emisor no espera ACK |
| **Heartbeats** | Conexión persistente, stateful | Stateless: cada heartbeat es autónomo, sin conexión |
| **Log shipping** | Backpressure del kernel TCP frena al emisor | El emisor dispara a máxima velocidad, el receptor procesa lo que puede |
| **Late binding** | Conexión punto a punto fija | Un agente puede descubrir nuevos peers en runtime sin reconfiguración |

### Multicast — Service Discovery sin orquestador

```
┌──────────┐                              ┌──────────┐
│ Agente A │──── DISCOVER (239.1.1.1) ───→│ Agente B │
│          │                              │          │
│          │←─── RESPONSE (unicast) ──────│          │
│          │                              │          │
│          │←─── RESPONSE (unicast) ──────│ Agente C │
│          │                              │          │
│          │←─── RESPONSE (unicast) ──────│ Agente D │
└──────────┘                              └──────────┘

1 frame DISCOVER  →  N responses unicast
Sin registry central, sin DNS, sin archivos de configuración.
```

El TTL multicast define el alcance:

| TTL | Alcance | Uso |
|-----|---------|-----|
| 0 | Mismo host | Agent-to-sidecar local |
| 1 | Mismo subnet | Microservicios en un cluster |
| 32 | Mismo site | Multi-rack en un datacenter |
| 64 | Misma región | Multi-AZ |
| 255 | Global | Teórico (rara vez usado) |

### API — Rust

```rust
use lumen::datagram::DatagramTransport;

// Receptor (escucha en puerto fijo)
let mut rx = DatagramTransport::bind("127.0.0.1:9999")?;
while let Some((data, src)) = rx.recv_frame()? {
    // data: &[u8] con el frame LUMEN completo
    println!("Frame de {}: {} bytes", src, data.len());
}

// Emisor (puerto efímero)
let tx = DatagramTransport::bind("127.0.0.1:0")?;
tx.send_frame_to(&frame_bytes, "127.0.0.1:9999".parse()?)?;

// Multicast
rx.join_multicast("239.1.1.1", None)?;
tx.set_multicast_ttl(1)?;
tx.send_frame_to(&discover_frame, "239.1.1.1:9999".parse()?)?;
```

### API — TypeScript

```typescript
import {
  DatagramTransport,
  buildDgram,
  parseDgram,
  TYPE_HEARTBEAT,
} from "@lumen/mcp-transport";

// Receptor
const rx = new DatagramTransport({ bindPort: 9999 });
await rx.bind();
rx.onMessage = (data, rinfo) => {
  const result = parseDgram(data);
  if (result.kind === "complete") {
    console.log(`Frame 0x${result.frame.frameType.toString(16)} de ${rinfo.address}`);
  }
};

// Emisor
const tx = new DatagramTransport();
await tx.bind();
const frame = buildDgram(TYPE_HEARTBEAT, 0, Buffer.from("ping"));
await tx.send(frame, 9999, "127.0.0.1");

// Multicast
rx.addMulticastMembership("239.1.1.1");
tx.setMulticastTTL(1);
await tx.send(frame, 9999, "239.1.1.1");
```

### Límites y garantías

| Propiedad | Valor |
|---|---|
| **Max datagram payload** | 65,507 bytes (65,535 − 8 UDP − 20 IP) |
| **Max frame payload** | 65,500 bytes (65,507 − 7 Hyb128+TYPE+FLAGS) |
| **Orden** | ❌ No garantizado |
| **Entrega** | ❌ No garantizada (best-effort) |
| **Duplicados** | ❌ Posibles (la red puede reenviar) |
| **Modo I/O** | No bloqueante (Rust: `set_nonblocking(true)`) |

### Benchmark — dgram-shootout (Rust)

5 escenarios, `cargo run --bin dgram-shootout`:

| Escenario | Métrica |
|---|---|
| **S1: Roundtrip** | Ping-pong UDP para payloads 16B → 65KB. Mide RTT real con eco servidor/cliente en hilos separados |
| **S2: Unidireccional** | Fire-and-forget a máxima velocidad. Mide throughput sin esperar ACK |
| **S3: Heartbeat** | Ping-pong con payload mínimo (8B). Mide el caso más pequeño posible |
| **S4: Parse overhead** | Build → send → recv → parse. Perfilado del ciclo completo del datagrama |
| **S5: Max payload** | Stress test con frames de 65,500 bytes. Verifica integridad bajo carga |

### Cobertura de tests

| Lenguaje | Tests | Runner |
|---|---|---|
| **Rust** | 5 escenarios (S1–S5) | `cargo run --bin dgram-shootout` |
| **TypeScript** | **13/13** ✅ | `node --test dist/dgram.test.js` |

> **Conclusión:** El Nivel 3 no compite con TCP — lo complementa. Usa Nivel 1 (stdio/TCP) para RPC request/response y streaming de tokens. Usa Nivel 3 (UDP/multicast) para descubrimiento, telemetría, heartbeats y log shipping. La ausencia de handshake TCP y la capacidad multicast hacen de LUMEN Nivel 3 la capa ideal para **comunicación many-to-many sin orquestador central**.

---

## ⚖️ Niveles 1, 2 y 3 — Guía de elección

Cada nivel de transporte resuelve un problema distinto. No hay un «mejor» nivel — hay un nivel **correcto para cada carga de trabajo**.

### Jerarquía de latencia

Latencia *round-trip* estimada para un heartbeat (~90 bytes) en loopback local:

```
  Nivel 2 (SHM)        ▏ ~200–500 ns   (ring buffer lock-free, sin kernel)
  Nivel 3 (UDP)        ▎ ~20–50 µs     (syscall sendto/recvfrom, sin handshake)
  Nivel 1 (TCP)        ▍ ~90–170 µs    (3-way handshake ya pagado en la conexión)
```

Y para payloads grandes (5–64 KB):

```
  Nivel 2 (SHM)        ▏ ~2–10 µs      (memcpy directo, ~10–20 GB/s)
  Nivel 3 (UDP)        ▎ ~80–120 µs    (datagrama único, sin fragmentación IP)
  Nivel 1 (TCP)        ▍ ~160–180 µs   (segmentación TCP + ACKs)
```

> ⚠️ Las cifras de Nivel 2 y 3 son **esperadas** basadas en el diseño (ring buffer lock-free, syscall única por datagrama). Ejecuta `cargo run --bin shm-shootout` y `cargo run --bin dgram-shootout` para los números reales en tu máquina.

### Matriz de decisión

| Criterio | Nivel 1 — Stream | Nivel 2 — SHM | Nivel 3 — Datagram |
|---|---|---|---|
| **Conexión** | Sí (TCP handshake, ~0.5–3 ms) | Sí (mmap + setup ring, ~1–5 ms) | **No** (stateless) |
| **Orden** | ✅ Garantizado | ✅ Garantizado (SPSC ring) | ❌ No garantizado |
| **Entrega** | ✅ Garantizada | ✅ Garantizada (buffer en RAM) | ❌ Best-effort |
| **Latencia típica** | ~100–700 µs (kernel TCP) | **~0.2–10 µs** (user-space puro) | ~20–120 µs (syscall única) |
| **Throughput** | ~50–500 MB/s (TCP stack) | **~10–20 GB/s** (ancho de banda RAM) | ~100–500 MB/s (NIC/kernel) |
| **Topología** | 1:1 (point-to-point) | 1:1 (procesos en misma máquina) | **1:N, N:M** (multicast nativo) |
| **Multi-máquina** | ✅ Sí | ❌ Solo misma máquina | ✅ Sí |
| **Fire-and-forget** | ❌ TCP fuerza ACKs | ❌ Ring buffer es síncrono | ✅ Natural |
| **Descubrimiento** | ❌ Necesitas conocer IP:puerto | ❌ Necesitas path conocido | ✅ **Multicast DISCOVER** |
| **CPU overhead** | Medio (copia kernel↔user) | **Mínimo** (zero-copy, memcpy) | Bajo (syscall por datagrama) |
| **Caso ideal** | RPC + streaming de tokens | **Archivos grandes entre procesos** | Telemetría + heartbeats + discovery |

### Elección por carga de trabajo

```
                    ┌─────────────────────────────────────────────┐
                    │ ¿Los procesos están en la misma máquina?     │
                    └─────────────────────────────────────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
                   Sí            No importa       No
                    │              │              │
            ┌───────┴───────┐      │      ┌───────┴───────┐
            │ ¿Payload >1KB?│      │      │ ¿Necesitas     │
            └───────────────┘      │      │  descubrimiento│
            │         │           │      │  automático?   │
            ▼         ▼           │      └───────────────┘
           Sí        No           │          │         │
            │         │           │         Sí        No
            ▼         ▼           │          │         │
        ┌────────┐ ┌────────┐    │     ┌────────┐ ┌────────┐
        │Nivel 2 │ │Nivel 1 │    │     │Nivel 3 │ │Nivel 1 │
        │  SHM   │ │ (TCP)  │    │     │  UDP   │ │ (TCP)  │
        └────────┘ └────────┘    │     └────────┘ └────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
               ¿Garantía     ¿Fire-and-   ¿Ambos
                de entrega?   forget?     procesos
                    │            │         locales?
                    ▼            ▼            ▼
                Nivel 1      Nivel 3      Nivel 2
                 (TCP)        (UDP)        (SHM)
```

### Combinar niveles en la práctica

Un agente LUMEN típico usa **los tres niveles simultáneamente**:

| Tarea | Nivel | Por qué |
|---|---|---|
| `tools/call` request/response | **Nivel 1** (TCP) | Garantía de entrega, orden, streaming de resultados |
| `llm/stream` tokens | **Nivel 1** (TCP) | Orden estricto de tokens, backpressure del kernel |
| Indexación de workspace (archivos >1 KB) | **Nivel 2** (SHM) | Zero-copy: 10–20 GB/s sin tocar el stack TCP |
| Heartbeats (keep-alive) | **Nivel 3** (UDP) | Stateless, sin conexión, fire-and-forget |
| Service discovery (¿qué agentes hay?) | **Nivel 3** (multicast) | Una trama DISCOVER → N respuestas, sin registry |
| Telemetría / métricas | **Nivel 3** (UDP) | Alto throughput, pérdida tolerada |
| Log shipping | **Nivel 3** (UDP) | Sin backpressure, el receptor filtra lo que puede |

> **Regla de oro:** Si necesitas que el mensaje llegue sí o sí → Nivel 1. Si necesitas que llegue a máxima velocidad → Nivel 2. Si necesitas que llegue a muchos destinos sin configurar cada uno → Nivel 3.

---

## 🛠️ Workspace Indexing Shootout (Cadencia)

Simula la carga real de **Cadencia** analizando un proyecto: lee todos los archivos fuente del directorio y los serializa como frames MCP. Medido con `cargo run --bin workspace-shootout`:

```
╔══════════════════════╤══════════════╤══════════════╤═══════════════╗
║ Metric               │ JSON-RPC     │ LUMEN        │ Advantage      ║
╠══════════════════════╪══════════════╪══════════════╪═══════════════╣
║ Encode time          │    0.024 s   │    0.004 s   │    5.62× FASTER ║
║ Throughput           │     8.6 MB/s │    45.3 MB/s │    5.25× MORE   ║
║ Time per file        │    1.062 ms  │    0.189 ms  │    5.62× FASTER ║
║ Wire bytes (total)   │     0.21 MB  │     0.20 MB  │    6.6% LESS   ║
╚══════════════════════╧══════════════╧══════════════╧═══════════════╝

  Proyección 5,000 archivos → JSON-RPC: 5.3s  |  LUMEN: 0.9s  |  5.6× faster
  Con archivos >100KB (source code real) → hasta 7× faster (ver S2)
```

> **Para Cadencia:** El 80% del tiempo de indexación de un workspace se va en serializar strings largos con escapes JSON (`\"`, `\n`, `\t`). LUMEN copia los bytes crudos sin tocarlos.

---

## 🔧 Rust FFI (C ABI) — Native Bindings

El crate Rust exporta una interfaz C estable (`cdylib`) con 10 funciones `extern "C"`:

### Compresión (5 funciones)

| Función | Firma | Descripción |
|---------|-------|-------------|
| `lumen_compress` | `(data, len, out, outLen) → i32` | Comprime JSON → LUMEN binario |
| `lumen_decompress` | `(data, len, out, outLen) → i32` | Descomprime LUMEN binario → JSON |
| `lumen_free` | `(ptr)` | Libera buffer asignado por Rust |
| `lumen_version` | `() → *const c_char` | Versión de la librería |
| `lumen_error_message` | `() → *const c_char` | Último mensaje de error |

### Zero-Copy Shared Memory (5 funciones, Nivel 2)

| Función | Firma | Descripción |
|---------|-------|-------------|
| `lumen_shm_create` | `(name, name_len, size) → *ShmOpaque` | Crea región SHM (servidor) |
| `lumen_shm_open` | `(name, name_len, size) → *ShmOpaque` | Abre región SHM (cliente) |
| `lumen_shm_write_frame` | `(h, side, data, data_len) → i32` | Escribe frame en ring buffer |
| `lumen_shm_read_frame` | `(h, side, buf, buf_cap, out_len) → i32` | Lee frame del ring buffer |
| `lumen_shm_close` | `(h)` | Cierra y libera la región SHM |

```c
// Ejemplo desde C
int32_t len = lumen_compress(json_bytes, json_len, &out, &out_len);
```

La FFI permite que cualquier lenguaje con soporte C FFI (Node, Python, C#, Go, Zig, etc.)
se beneficie del compresor Rust de alto rendimiento sin reimplementar el protocolo.

### Node.js (koffi)

```typescript
import { compressValueFFI, decompressValueFFI } from "@lumen/mcp-transport";

const compressed = compressValueFFI({ jsonrpc: "2.0", method: "tools/list" });
const original = decompressValueFFI(compressed);
```

Usa [koffi](https://koffi.dev/) (pure JS, zero build) para cargar `lumen.dll` / `liblumen.so`.

### Node.js — Zero-Copy SHM (Nivel 2)

```typescript
import { ShmTransportFFI } from "@lumen/mcp-transport";

// Servidor
const server = ShmTransportFFI.createServer("/lumen-shm-demo");
server.writeFrame(Buffer.from("hello from server"));
const req = server.readFrame();  // null si no hay datos

// Cliente (otro proceso)
const client = ShmTransportFFI.openClient("/lumen-shm-demo");
client.writeFrame(Buffer.from("hello from client"));
const res = client.readFrame();  // "hello from server"

server.close(); client.close();
```

Comunicación zero-copy entre procesos via ring buffers lock-free SPSC sobre
memoria compartida nativa (Rust `ShmRegion` → koffi FFI → Node.js `ShmTransportFFI`).

### C# (.NET 9 P/Invoke)

```csharp
using Lumen;

var compressed = LumenFFI.CompressValue(jsonElement);
var decompressed = LumenFFI.DecompressValue(compressed);
```

P/Invoke con `[DllImport("lumen")]` y `CallingConvention.Cdecl`. Zero dependencies.

---

## 🎯 C# Implementation (.NET 9)

```bash
cd implementations/csharp
dotnet run -c Release
```

### Resultados — 17/17 roundtrip, 28/28 golden, 0 fallos

| Suite | Resultado |
|-------|-----------|
| Roundtrip (17 casos) | 17/17 ✅ |
| FFI roundtrip + cross-check | 17/17 ✅ |
| Golden binary (28 archivos) | 28/28 ✅ |
| Golden FFI | 28/28 ✅ |

### Benchmark — .NET 9, C# native vs P/Invoke FFI

| Payload | Op | Native | FFI | Speedup |
|---------|-----|--------|-----|---------|
| MCP tools/list | compress | 2.1µs | 3.6µs | 0.6× |
| MCP tools/list | decompress | 6.5µs | 5.2µs | 1.2× |
| MCP initialize | compress | 6.7µs | 7.2µs | 0.9× |
| MCP initialize | decompress | 18.0µs | 17.8µs | 1.0× |
| MCP tools ×20 | compress | 234.9µs | 244.5µs | 1.0× |
| MCP tools ×20 | **decompress** | 463.7µs | 161.8µs | **2.9×** |
| LLM response | decompress | 14.1µs | 8.9µs | **1.6×** |
| **TOTAL** | compress | 250.2µs | 263.1µs | 1.0× |
| **TOTAL** | **decompress** | 502.3µs | 193.6µs | **2.6×** |

> **FFI decompress es 2.6× más rápido.** La FFI devuelve el JSON directamente desde Rust,
> mientras que el decoder nativo C# construye árboles intermedios (`Dictionary<string, object?>`,
> `object[]`) y los re-serializa con `JsonSerializer`. La FFI de compresión es equivalente
> (1.0×) — el encoder C# nativo ya está optimizado con `ArrayPool<byte>` y `stackalloc`.

### Detalles de implementación

| Característica | Detalle |
|----------------|---------|
| **Encoder nativo** | `System.Text.Json` + `ArrayPool<byte>` + `stackalloc` — zero alloc en el hot path |
| **Decoder nativo** | `Dictionary<string, object?>` / `object[]` intermedios → `JsonSerializer.SerializeToElement` |
| **FFI** | P/Invoke `[DllImport]`, `CallingConvention.Cdecl`, `nint` para punteros |
| **Diccionario** | `Dict.cs` — 128 entradas estáticas con lookup O(1) y reverse lookup |
| **Hyb128** | `Hyb128.cs` — encode/decode con los 4 modos (00/10/11/01) |

---

## 📊 FFI Benchmark Multi-Lenguaje

Comparativa de rendimiento de la FFI Rust vs implementación nativa en cada lenguaje:

| Lenguaje | Compress (FFI vs native) | Decompress (FFI vs native) | Librería FFI |
|----------|--------------------------|----------------------------|--------------|
| **Node.js** | **4.4× faster** 🔥 | 1.0× | [koffi](https://koffi.dev/) v3.0.2 |
| **C# (.NET 9)** | 1.0× | **2.6× faster** 🔥 | P/Invoke `[DllImport]` |
| **Python** | 0.5× (slower) | 0.5× (slower) | `ctypes` (stdlib) |

> **Node.js:** La FFI brilla en compresión porque `compressValue` TS pasa por el JIT de V8
> mientras que Rust corre nativo. En decompress, `decompressValue` TS ya está muy optimizado
> y la FFI no añade ventaja.
>
> **C#:** La FFI gana en decompress porque Rust devuelve el JSON ya parseado, ahorrando
> la reconstrucción de árboles intermedios. En compress, el encoder nativo C# con
> `ArrayPool<byte>` iguala a Rust.
>
> **Python:** `ctypes` tiene overhead alto (marshalling de objetos Python ↔ C).
> Para payloads pequeños, el overhead domina y la FFI es más lenta que el encoder
> nativo de CPython (que ya está en C).

---

## 🐘 PHP Implementation (lumen-php)

```bash
cd implementations/php
php tests/e2e_test.php          # cross-implementation e2e: 217/217
php bench.php > bench_out.json  # benchmark suite (74 resultados)
```

### Resultados — 217/217 e2e tests pasando (PHP 8.5.7)

| Suite | Tests |
|-------|-------|
| Compress roundtrip + golden binary | 27+28 ✅ |
| Hyb128 encode/decode | 22 ✅ |
| Frame parse | 22 ✅ |
| Compressed frame integration | 118 ✅ |
| **Total** | **217/217 ✅** |

### Benchmark — PHP 8.5.7: json_encode/decode vs compress/decompress

| Payload | json encode | LUMEN encode | Ratio | json decode | LUMEN decode | Ratio |
|---------|------------|--------------|-------|------------|--------------|-------|
| initialize (157B→91B) | 1.4µs | 33.4µs | 0.04× | 6.5µs | 29.0µs | 0.22× |
| tools_list (835B→386B) | 9.4µs | 170.6µs | 0.06× | 39.1µs | 215.7µs | 0.18× |
| llm_request (323B→166B) | 5.3µs | 62.2µs | 0.08× | 15.8µs | 93.3µs | 0.17× |
| error_response (175B→95B) | 2.1µs | 26.3µs | 0.08× | 6.2µs | 32.0µs | 0.19× |
| **big_result (5193B→5104B)** | 14.2µs | 41.6µs | **0.34×** | 30.3µs | 43.7µs | **0.69×** |

> **PHP json_encode/decode gana en velocidad** — mismo patrón que Python: `json_encode` y
> `json_decode` son extensiones C del motor Zend (12–24× más rápidas para payloads pequeños),
> mientras que `compress`/`decompress` son bytecode PHP interpretado. El gap se cierra
> con payloads grandes: en `big_result` (5 KB), LUMEN decode es solo **1.44× más lento**
> porque evita el escaping de strings.
>
> **La ventaja de LUMEN en PHP está en el wire size** (46–54% de ahorro en payloads MCP
> típicos) y en la **compatibilidad binaria cruzada** con Python, TypeScript, Rust y C#.

### Wire size PHP (mismo protocolo, mismos bytes)

| Payload | JSON | LUMEN | Ahorro |
|---------|------|-------|--------|
| initialize | 157 B | 91 B | **42%** |
| tools_list | 835 B | 386 B | **54%** |
| llm_request | 323 B | 166 B | **49%** |
| error_response | 175 B | 95 B | **46%** |
| big_result | 5,193 B | 5,104 B | 2% |

### Hyb128 — PHP 8.5.7

| Operación | Mejor caso | Peor caso (mode >1B) |
|-----------|-----------|---------------------|
| **Encode** | 4.3M/s (modo 1B) | 1.5M/s (modo 3/5B) |
| **Decode** | 2.8M/s (modo 1B) | 0.5M/s (modo 5B) |

> PHP Hyb128 es 10–20× más lento que TypeScript por ser bytecode puro (vs JIT V8).
> El framing con Content-Length es más rápido en PHP que Hyb128 (al contrario que en TS),
> porque `preg_match`/`substr` son funciones C mientras que Hyb128 es PHP puro.

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

## 📊 TypeScript Benchmark Suite

**122 benchmarks en 18 categorías**, ejecutados con `node --expose-gc --import tsx src/bench.ts`. Resultados en `implementations/typescript/bench_results_full.json`.

### 🧪 Test Suite — 755+ tests pasando

| Suite | Tests | Lenguaje | Runner |
|---|---|---|---|
| LUMEN Rust core | **68/68** | Rust | `cargo test` |
| FrameAssembler stress | **17/17** | TypeScript | `node --test` |
| ZeroAllocDecompressor | **79/79** | TypeScript | `node --test` |
| SHM FFI (Level 2) | **10/10** | TS ↔ Rust | `node --test dist/shm_ffi.test.js` |
| Datagram (Level 3) | **13/13** | TypeScript | `node --test dist/dgram.test.js` |
| **TS e2e cross-impl** | **217/217** | TypeScript | `npx tsx --test src/e2e.test.ts` |
| CadenciaBridge integración | **3/3** | TS ↔ Rust | `node --test` |
| Python unit tests | **94/94** | Python | `pytest` |
| C# roundtrip + golden | **17/17 + 28/28** | C# (.NET 9) | `dotnet run` |
| C# FFI (P/Invoke) | **17/17 + 28/28** | C# ↔ Rust | `dotnet run` |
| PHP e2e (roundtrip + golden + frames) | **217/217** | PHP 8.5 | `php tests/e2e_test.php` |

### 🔗 Cross-Implementation E2E — 588 tests

Golden file testing entre las 5 implementaciones (Python genera, resto validan):

| Implementación | E2E Tests | Scope | Estado |
|---|---|---|---|
| **Python** | 89/89 | 28 vectores × golden generate/validate | ✅ Genera golden binaries |
| **TypeScript** | 217/217 | Suite completa (compress + Hyb128 + Frame + integr.) | ✅ Match binario + cross-decode |
| **Rust** | 9/9 | 9 `#[test]` fn à ~28 iters c/u (~250 assertions) | ✅ Match semántico + Hyb128 + frames |
| **C# (.NET 9)** | 28/28 | Compress/decompress golden (sin Hyb128/Frame) | ✅ Match binario byte-por-byte |
| **C# FFI (P/Invoke)** | 28/28 | Compress/decompress via Rust FFI | ✅ Match binario byte-por-byte |
| **PHP 8.5** | 217/217 | Suite completa (compress + Hyb128 + Frame + integr.) | ✅ Match binario + frame integration |

> **¿Por qué PHP y TS tienen 217 y Rust solo 9?**
> PHP y TS usan la misma estructura de e2e: 28 vectores × 3 tests + 8 stability + 11 Hyb128
> + 36 frame roundtrip + 72 frame compat + 6 integration = **217 tests individuales**.
> Rust usa el convenio `#[test]` con una función por tipo de test que itera internamente
> sobre todos los vectores — misma cobertura, conteo diferente.
> C# tiene un harness enfocado en benchmark, solo valida compress/decompress.

Los 28 vectores compartidos en `tests/e2e/shared_vectors.json` cubren todos los
value types LUMEN (null, bool, int, float, string, array, object) y payloads MCP
reales (initialize, tools/list, llm_request, error_response).

### 🥊 TypeScript — Dónde gana LUMEN

La implementación TypeScript de LUMEN prioriza **tamaño de wire** y **framing eficiente**. Para escenarios de alta velocidad de CPU, se usa la FFI Rust nativa (`compressValueFFI`, **4.4× más rápido**) o el `ZeroAllocDecompressor` (**54% menos GC**). Los benchmarks de velocidad pura están en las secciones Rust de arriba (shootout, heap-shootout, concurrent, IPC, workspace).

### ⚡ A. FrameAssembler — Zero-Allocation Streaming Parser

Parser binario con buffers pre-asignados. Mide frames/segundo y throughput en MB/s para 5 tamaños × 7 chunk sizes:

| Payload | fps (chunk=full) | MB/s |
|---|---|---|
| 16 B (tiny) | 57,789 | 1.10 |
| 256 B (small) | 164,373 | 41.06 |
| 4 KB (medium) | 227,340 | **888** |
| 64 KB (large) | 18,429 | **1,152** |
| 256 KB (xlarge) | 4,868 | **1,217** |

> **Satúrase a ~1.2 GB/s** a partir de 4 KB. El parser no hace allocaciones — reusa buffers `Uint8Array` pre-asignados.

#### Chunk-size stress (payload=4KB)

| Chunk | fps | Interpretación |
|---|---|---|
| 1 byte (torture) | 114,599 | Peor caso: 4096 llamadas a `push()` |
| 16 bytes | 259,510 | Fragmentación típica de red |
| 64 bytes | 282,321 | Paquete UDP típico |
| 256 bytes | 280,788 | Buffer de lectura estándar |
| 4 KB (full) | 227,340 | Mejor caso: 1 frame = 1 chunk |

> Incluso en **torture test (1 byte/chunk)**, el parser mantiene 114K fps — solo 2× más lento que el caso ideal.

### 📦 B. Compresión — JSON vs LUMEN (wire bytes)

Mismos payloads MCP reales, medidos con el codec `compress.ts`:

| Escenario MCP | JSON | LUMEN | Ratio | Ahorro |
|---|---|---|---|---|
| `initialize` | 157 B | 92 B | **58.6%** | 65 B (41.4%) |
| `tools/list` | 835 B | 386 B | **46.2%** | 449 B (53.8%) |
| `llm_request` | 323 B | 166 B | **51.4%** | 157 B (48.6%) |
| `error_response` | 175 B | 95 B | **54.3%** | 80 B (45.7%) |
| `big_result` (5 KB) | 5,193 B | 5,104 B | **98.3%** | 89 B (1.7%) |

> **Media en payloads MCP típicos: 47–55% de compresión.** Sólo en payloads masivos sin claves repetidas (>5 KB) el overhead de tags binarios se diluye.

### 🔢 C. Hyb128 Codec — Encode/Decode

Microbenchmarks del codec de longitud híbrida. 11 valores cubriendo modos 00, 10, 11:

| Operación | Mejor caso | Peor caso | Promedio |
|---|---|---|---|
| **Decode** | 49.3M/s (`0`, mode 00) | 8.3M/s (`1`, mode 00) | ~30M/s |
| **Encode** | 30.7M/s (`0`, mode 00) | 10.1M/s (`63`, boundary) | ~20M/s |

> Decode es **~1.5× más rápido** que encode. Encode sufre en boundaries entre modos por el branching.

### 📖 D. Dict O(1) Lookup

| Métrica | Valor |
|---|---|
| `Map.get()` O(1) | **20.8M/s** |
| Operaciones | 1,000,000 |
| Duración | ~48 ms |

### 🔗 TypeScript ↔ Rust Integration (CadenciaBridge)

El sidecar Rust se ejecuta como child process. TypeScript envía comandos JSON por stdin, Rust devuelve frames LUMEN:

| Prueba | Resultado |
|---|---|
| Ping handshake | ✅ 21.8 ms |
| Index 30K archivos | ✅ 17.6 ms (encode: 163 µs) |
| Graceful shutdown | ✅ 4.4 ms |

---

### 📏 H. Framing: Content-Length vs Hyb128 (header parse)

| Value | CL ops/s | Hyb128 ops/s | Ratio | Bytes (CL→Hyb) |
|---|---|---|---|---|
| 0 | 6.28M | **37.0M** | 5.9× | 21→1 |
| 42 | 4.35M | **15.5M** | 3.6× | 22→1 |
| 255 | 5.15M | **38.9M** | 7.6× | 23→3 |
| 1024 | 5.92M | **42.2M** | 7.1× | 24→3 |
| 65535 | 5.69M | **45.3M** | 8.0× | 25→3 |
| 1000000 | 5.64M | **38.7M** | 6.9× | 27→5 |

> 🏆 **LUMEN arrasa**: Hyb128 parseo es **3.6–8× más rápido** y usa **5–21× menos bytes** que Content-Length. El parser sabe en 1 ciclo cuánto saltar.

---

### 🪢 I. String Escape — JSON.stringify vs LUMEN raw copy

JSON.stringify debe inspeccionar **cada carácter** buscando `"`, `\`, `\n`, `\t`, `\r` y escaparlos con `\`. LUMEN hace copia binaria cruda — sin inspección ni expansión.

| Payload | JSON ops/s | LUMEN ops/s | Speedup | Wire (JSON→LUMEN) |
|---|---|---|---|---|
| code_json_1KB | 125,893 | 117,189 | 0.93× | 1,589→1,398 (-12%) |
| **quotes_heavy** | 36,589 | 79,982 | **2.19×** 🔥 | 8,025→4,018 (-50%) |
| newlines_tabs | 17,933 | 20,206 | **1.13×** | 15,014→13,007 (-13%) |
| backslash_hell | 47,635 | 71,755 | **1.51×** | 6,020→3,013 (-50%) |
| mixed_escape_4KB | 42,401 | 53,798 | **1.27×** | 5,594→4,447 (-20%) |

> 🏆 **LUMEN gana 4 de 5 escenarios.** En `quotes_heavy` (strings con muchas comillas), LUMEN es **2.19× más rápido** y produce la **mitad de bytes**. La única derrota es `code_json_1KB` (0.93×), donde hay pocos caracteres especiales y el overhead del formato binario no se amortiza. **La copia binaria cruda es estructuralmente superior al modelo de escaping de JSON.**

### 🧠 ZeroAllocDecompressor — 54% menos GC

El decoder TypeScript original (`decompressValue`) era recursivo y generaba objetos temporales (tags, string fragments, frames de pila). La versión optimizada (`ZeroAllocDecompressor`, `src/zeroalloc.ts`) usa un loop iterativo con stack pre-asignado y buffers compartidos — **sin ningún objeto intermedio en el hot path**.

Resultados medidos con `node --expose-gc` sobre payload de 500 tools:

| Decoder | Heap Δ | vs JSON | Garbage eliminada |
|---|---|---|---|
| `JSON.parse` (C++ nativo) | ~380 KB | 1.0× | baseline |
| `decompressValue` (recursivo original) | ~3,030 KB | 8.0× | — |
| **`ZeroAllocDecompressor`** | **~1,400 KB** | **3.7×** | **🔥 54% menos** |

**Optimizaciones aplicadas:**
- `TextDecoder` compartido a nivel de módulo — cero allocs por string
- Hyb128 inline — sin alocar `{ value, headerLen }` intermedios
- Loop iterativo + pool de frames — cero recursión, stack reutilizado
- Dict refs compartidas — claves del diccionario devuelven la misma referencia

> 🏆 **54% menos basura sin tocar el protocolo ni añadir build steps.** La basura restante (~1 MB) son los strings únicos reales y las vistas `subarray()` para UTF-8 — datos que también retiene `JSON.parse`. La FFI Rust (`compressValueFFI`) complementa con **4.4× más velocidad** en encode.

### 🆚 Resumen comparativo

| # | Métrica | Ganador | Detalle |
|---|---|---|---|
| 1 | Wire size | **LUMEN** | 30–83% menor (Rust shootout + sección B) |
| 2 | Encode speed | **LUMEN** (Rust/FFI) | Rust: 1.6–7×, FFI TS: 4.4× |
| 3 | Framing parse | **LUMEN** | Hyb128 3.6–8× vs Content-Length |
| 4 | String escape | **LUMEN** | Raw copy binaria, 1.1–2.2× más rápido |
| 5 | GC pressure | **LUMEN** (ZeroAlloc) | 54% menos basura vs decoder recursivo |
| 6 | Streaming | **LUMEN** | ~12 B/token vs ~75 B/token JSON |
| 7 | Zero-Copy | **LUMEN** | SHM Nivel 2 (mmap/ring buffers) |

---

## 📝 Licencia

MIT
