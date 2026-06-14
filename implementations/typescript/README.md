# @lumen/mcp-transport

LUMEN binary transport for the Model Context Protocol (MCP) SDK.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  MCP Client / Server (your code)                 │
│  ┌───────────────────────────────────────────┐   │
│  │  @modelcontextprotocol/sdk                 │   │
│  │  ┌─────────────────────────────────────┐  │   │
│  │  │  Transport interface                 │  │   │
│  │  │  ┌───────────────────────────────┐  │  │   │
│  │  │  │  @lumen/mcp-transport  ← YOU  │  │  │   │
│  │  │  │  LumenStdioTransport           │  │  │   │
│  │  │  │  LumenWebSocketTransport       │  │  │   │
│  │  │  └───────────────────────────────┘  │  │   │
│  │  └─────────────────────────────────────┘  │   │
│  └───────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

## Protocol Negotiation (Handshake)

When a LUMEN transport starts, it sends a **capability probe** before
the MCP initialize handshake:

```
Client → Server:  [LUMEN_PROBE frame]  (binary)
  - TYPE: 0x0F (PROBE)
  - FLAGS: 0x00
  - PAYLOAD: {"v":1,"caps":["compression","streaming"]}

Server → Client:  [LUMEN_ACK frame]  (binary)
  - TYPE: 0x10 (PROBE_ACK)
  - FLAGS: 0x00
  - PAYLOAD: {"v":1,"caps":["compression","streaming"]}


  ... OR ...

Server does not respond with LUMEN_ACK within 500ms →
Client falls back to JSON-RPC transparently.
```

## Usage

```typescript
import { LumenStdioTransport } from "@lumen/mcp-transport";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";

// Drop-in replacement — same API as StdioClientTransport
const transport = new LumenStdioTransport({
  command: "python",
  args: ["mcp_server.py"],
  // Optional: force JSON-RPC (skip LUMEN negotiation)
  // forceJsonRpc: true,
});

const client = new Client(
  { name: "my-client", version: "1.0.0" },
  { capabilities: {} }
);

await client.connect(transport);
// If the server speaks LUMEN → binary frames (~3× faster)
// If not → falls back to JSON-RPC automatically
```

## API

### `LumenStdioTransport`

Drop-in replacement for `StdioClientTransport` from `@modelcontextprotocol/sdk`.

```typescript
class LumenStdioTransport implements Transport {
  constructor(options: {
    command: string;
    args?: string[];
    env?: Record<string, string>;
    cwd?: string;
    /** Skip LUMEN negotiation, use JSON-RPC directly */
    forceJsonRpc?: boolean;
    /** Probe timeout in ms (default: 500) */
    probeTimeoutMs?: number;
  });

  // Transport interface (compatible with MCP SDK)
  start(): Promise<void>;
  send(message: JSONRPCMessage): Promise<void>;
  close(): Promise<void>;
  onmessage: ((message: JSONRPCMessage) => void) | null;
  onerror: ((error: Error) => void) | null;
  onclose: (() => void) | null;
}
```

### `LumenWebSocketTransport`

WebSocket transport with LUMEN binary frames.
Ideal for cloud gateways (Cadencia → API Gateway → MCP servers).

```typescript
class LumenWebSocketTransport implements Transport {
  constructor(url: string, options?: {
    forceJsonRpc?: boolean;
    probeTimeoutMs?: number;
  });
  // ... same Transport interface
}
```

## Package structure

```
implementations/typescript/
├── README.md              ← this file
├── package.json
├── tsconfig.json
├── bench_results_full.json← cached benchmark results (122 entries)
└── src/
    ├── index.ts           ← public exports
    ├── transport.ts       ← LumenStdioTransport, LumenWebSocketTransport
    ├── negotiation.ts     ← LUMEN probe/ack handshake + fallback
    ├── hyb128.ts          ← Hyb128 encode/decode
    ├── frame.ts           ← Frame builder/parser
    ├── frame-assembler.ts ← Zero-allocation streaming frame reassembler
    ├── dict.ts            ← Dictionary (128 static + 127 session IDs, O(1) lookup)
    ├── compress.ts        ← Compact binary payload codec
    ├── compress_ffi.ts    ← FFI wrapper (Rust → Node via koffi, 4.4× faster)
    ├── shm_ffi.ts         ← SHM zero-copy transport (Nivel 2, FFI)
    ├── dgram.ts           ← Datagram UDP/multicast (Nivel 3)
    ├── zeroalloc.ts       ← ZeroAllocDecompressor (54% less GC)
    ├── cadencia.ts        ← Cadencia sidecar bridge client
    ├── bench.ts           ← Benchmark suite (122 benchmarks, 18 categories)
    ├── frame-assembler.test.ts  ← 17 stress tests
    ├── zeroalloc.test.ts        ← 79 correctness + safety tests
    ├── dgram.test.ts            ← 13 datagram tests (Nivel 3)
    ├── shm_ffi.test.ts          ← 10 SHM integration tests (Nivel 2)
    ├── e2e.test.ts              ← 217 cross-implementation E2E tests
    └── cadencia.integration.test.ts ← 3 integration tests (needs Rust binary)
```

## Status

| Component | Status |
|-----------|--------|
| `hyb128.ts` | 🟢 Done — encode/decode, mode 00/10/11, LEB128 fallback |
| `frame.ts` | 🟢 Done — build/parse, all 12 frame types + flags |
| `frame-assembler.ts` | 🟢 Done — zero-alloc streaming parser, 1.2 GB/s saturation |
| `dict.ts` | 🟢 Done — 128 static + 127 session IDs, O(1) resolve + lookup |
| `compress.ts` | 🟢 Done — 8 value tags, dict compression, 47-55% wire savings |
| `compress_ffi.ts` | 🟢 Done — Rust FFI via koffi, 4.4× faster encode |
| `shm_ffi.ts` | 🟢 Done — Nivel 2 SHM zero-copy, 10/10 tests |
| `dgram.ts` | 🟢 Done — Nivel 3 Datagram UDP/multicast, 13/13 tests |
| `zeroalloc.ts` | 🟢 Done — 54% less GC vs naive decoder (3.7× vs JSON) |
| `negotiation.ts` | 🟢 Done — probe/ack handshake, 500ms fallback to JSON-RPC |
| `transport.ts` | 🟢 Done — Stdio + WebSocket, auto LUMEN negotiation |
| `cadencia.ts` (sidecar) | 🟢 Prototyped — Rust `cadencia-bridge` + TS client |

## Benchmarks

**122 benchmarks in 18 categories** covering encode/decode speed, wire size, GC pressure, framing parse, string escape, and dict lookup. Run with:

```bash
node --expose-gc --import tsx src/bench.ts
```

Key results from the root [README](../../README.md#-typescript-benchmark-suite):
- **Wire size:** 47–55% smaller than JSON for MCP payloads
- **String escape:** 1.1–2.2× faster than `JSON.stringify` on hostile strings
- **GC pressure:** ZeroAllocDecompressor = 1,401 KB heap Δ vs 3,033 KB naive (54% reduction)
- **Framing:** Hyb128 parse 3.6–8× faster than Content-Length

## Test Suite

Core TS-only tests (96/96):

```bash
node --import tsx --test src/zeroalloc.test.ts src/frame-assembler.test.ts
```

Full suite (requires compiled Rust `cadencia-bridge` binary + `lumen.dll`):

```bash
node --import tsx --test src/*.test.ts   # +3 CadenciaBridge, +10 SHM FFI
node --test dist/dgram.test.js           # 13 datagram (Nivel 3)
node --test dist/e2e.test.js             # 217 cross-implementation E2E
```
