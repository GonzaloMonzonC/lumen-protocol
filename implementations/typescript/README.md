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
├── README.md           ← this file
├── package.json
├── tsconfig.json
└── src/
    ├── index.ts        ← public exports
    ├── transport.ts    ← LumenStdioTransport, LumenSSETransport,
    │                     LumenWebSocketTransport
    ├── negotiation.ts  ← LUMEN probe/ack handshake + fallback
    ├── hyb128.ts       ← Hyb128 encode/decode (TypeScript port)
    ├── frame.ts        ← Frame builder/parser (TypeScript port)
    ├── dict.ts         ← Dictionary (128 static IDs, Map for lookup)
    ├── compress.ts     ← Compact binary payload (TAG + dict)
    └── cadencia.ts     ← Cadencia sidecar bridge client
                         (spawns cadencia-bridge, JSON protocol)
```

## Status

| Component | Status |
|-----------|--------|
| `hyb128.ts` | 🔴 TODO |
| `frame.ts` | 🔴 TODO |
| `dict.ts` | 🔴 TODO |
| `compress.ts` | 🔴 TODO |
| `negotiation.ts` | 🔴 TODO |
| `transport.ts` | 🔴 TODO |
| `cadencia.ts` (sidecar) | 🟢 Prototyped in Rust (`cadencia-bridge`) |
