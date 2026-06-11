/**
 * Transport implementations — drop-in replacements for MCP SDK transports.
 *
 * Each transport implements the `Transport` interface from
 * `@modelcontextprotocol/sdk` and performs automatic LUMEN negotiation
 * on `start()`. If the remote peer doesn't respond to the LUMEN probe
 * within a configurable timeout, the transport falls back to JSON-RPC
 * transparently.
 */

import type { Transport, JSONRPCMessage } from "@modelcontextprotocol/sdk";

// ── Options ──────────────────────────────────────────────────────────────────

export interface LumenTransportOptions {
  /** Skip LUMEN negotiation entirely; use JSON-RPC directly. */
  forceJsonRpc?: boolean;
  /** Probe timeout in milliseconds (default: 500). */
  probeTimeoutMs?: number;
}

export interface LumenStdioOptions extends LumenTransportOptions {
  /** Command to spawn the MCP server process. */
  command: string;
  /** Arguments for the command. */
  args?: string[];
  /** Environment variables. */
  env?: Record<string, string>;
  /** Working directory. */
  cwd?: string;
}

// ── Stdio Transport ──────────────────────────────────────────────────────────

/**
 * Drop-in replacement for `StdioClientTransport` from `@modelcontextprotocol/sdk`.
 *
 * On `start()`, spawns the MCP server process and attempts LUMEN negotiation.
 * If the server responds with a LUMEN ACK frame, all subsequent communication
 * uses LUMEN binary frames. Otherwise, falls back to JSON-RPC.
 *
 * @example
 * ```typescript
 * import { LumenStdioTransport } from "@lumen/mcp-transport";
 * import { Client } from "@modelcontextprotocol/sdk/client/index.js";
 *
 * const transport = new LumenStdioTransport({
 *   command: "npx",
 *   args: ["-y", "@anthropic/mcp-server-filesystem", "/tmp"],
 * });
 *
 * const client = new Client(
 *   { name: "my-client", version: "1.0.0" },
 *   { capabilities: {} }
 * );
 * await client.connect(transport);
 * ```
 */
export class LumenStdioTransport implements Transport {
  // TODO: implement
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;

  constructor(_options: LumenStdioOptions) {
    throw new Error("LumenStdioTransport: not yet implemented");
  }

  async start(): Promise<void> {
    throw new Error("LumenStdioTransport: not yet implemented");
  }

  async send(_message: JSONRPCMessage): Promise<void> {
    throw new Error("LumenStdioTransport: not yet implemented");
  }

  async close(): Promise<void> {
    throw new Error("LumenStdioTransport: not yet implemented");
  }

  onmessage: ((message: JSONRPCMessage) => void) | null = null;
  onerror: ((error: Error) => void) | null = null;
  onclose: (() => void) | null = null;
}

// ── WebSocket Transport ──────────────────────────────────────────────────────

/**
 * LUMEN over WebSocket binary frames.
 *
 * Ideal for cloud gateways where the MCP server is behind a WebSocket
 * endpoint (e.g., Cadencia API Gateway → MCP servers).
 *
 * @example
 * ```typescript
 * const transport = new LumenWebSocketTransport("wss://api.cadencia.app/mcp");
 * ```
 */
export class LumenWebSocketTransport implements Transport {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;

  constructor(
    _url: string,
    _options?: LumenTransportOptions & { binaryFrames?: boolean }
  ) {
    throw new Error("LumenWebSocketTransport: not yet implemented");
  }

  async start(): Promise<void> {
    throw new Error("LumenWebSocketTransport: not yet implemented");
  }

  async send(_message: JSONRPCMessage): Promise<void> {
    throw new Error("LumenWebSocketTransport: not yet implemented");
  }

  async close(): Promise<void> {
    throw new Error("LumenWebSocketTransport: not yet implemented");
  }

  onmessage: ((message: JSONRPCMessage) => void) | null = null;
  onerror: ((error: Error) => void) | null = null;
  onclose: (() => void) | null = null;
}
