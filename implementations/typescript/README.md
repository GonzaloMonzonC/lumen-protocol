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
│  │  │  │  LumenSSETransport             │  │  │   │
│  │  │  │  LumenWSSTransport             │  │  │   │
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

### `LumenSSETransport`

Drop-in replacement for `SSEClientTransport`.

```typescript
class LumenSSETransport implements Transport {
  constructor(url: string, options?: {
    forceJsonRpc?: boolean;
    probeTimeoutMs?: number;
  });
  // ... same Transport interface
}
```

### `LumenWebSocketTransport`

New transport: WebSocket with LUMEN binary frames.
Ideal for cloud gateways (Cadencia → API Gateway → MCP servers).

```typescript
class LumenWebSocketTransport implements Transport {
  constructor(url: string, options?: {
    forceJsonRpc?: boolean;
    /** Send LUMEN frames as binary WebSocket messages */
    binaryFrames?: boolean; // default: true
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
    ├── hyb128.ts          ← Hyb128 encode/decode (TypeScript port)
    ├── frame.ts           ← Frame builder/parser (TypeScript port)
    ├── frame-assembler.ts ← Zero-allocation streaming frame reassembler
    ├── dict.ts            ← Dictionary (128 static IDs, O(1) lookup)
    ├── compress.ts        ← Compact binary payload codec
    ├── zeroalloc.ts       ← ZeroAllocDecompressor (Vía 1, 54% less GC)
    ├── cadencia.ts        ← Cadencia sidecar bridge client
    ├── bench.ts           ← Benchmark suite (122 benchmarks, 18 categories)
    ├── frame-assembler.test.ts  ← 17 stress tests
    ├── zeroalloc.test.ts        ← 79 correctness + safety tests
    └── cadencia.integration.test.ts ← 3 integration tests (needs Rust binary)
```

## Status

| Component | Status |
|-----------|--------|
| `hyb128.ts` | 🟢 Done — encode/decode, mode 00/10/11, LEB128 fallback |
| `frame.ts` | 🟢 Done — build/parse, all 12 frame types + flags |
| `frame-assembler.ts` | 🟢 Done — zero-alloc streaming parser, 1.2 GB/s saturation |
| `dict.ts` | 🟢 Done — 128 static IDs, O(1) resolve + lookup |
| `compress.ts` | 🟢 Done — 8 value tags, dict compression, 47-55% wire savings |
| `zeroalloc.ts` | 🟢 Done — Vía 1: 54% less heap vs naive decoder (3.7× vs JSON) |
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
- **String escape (Asalto 2):** 1.1–2.2× faster than `JSON.stringify` on hostile strings
- **GC pressure (Asalto 3):** ZeroAllocDecompressor = 1,401 KB heap Δ vs 3,033 KB naive (54% reduction)
- **Framing:** Hyb128 parse 3.6–8× faster than Content-Length

## Test Suite

**96/96 passing** (79 zero-alloc + 17 frame-assembler) without the Rust sidecar:

```bash
node --import tsx --test src/zeroalloc.test.ts src/frame-assembler.test.ts
```

Full suite (requires compiled `cadencia-bridge` binary):

```bash
node --import tsx --test src/*.test.ts   # +3 CadenciaBridge integration tests
```
