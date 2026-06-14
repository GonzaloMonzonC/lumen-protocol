/**
 * Transport implementations — drop-in replacements for MCP SDK transports.
 *
 * Each transport implements the `Transport` interface from
 * `@modelcontextprotocol/sdk` and performs automatic LUMEN negotiation
 * on `start()`. If the remote peer doesn't respond to the LUMEN probe
 * within a configurable timeout, the transport falls back to JSON-RPC
 * transparently.
 */

import { spawn, ChildProcess } from "child_process";
import { createInterface, Interface } from "readline";
import { buildProbe, parseAck, DEFAULT_PROBE_TIMEOUT_MS } from "./negotiation.js";
import {
  buildFrame,
  buildSize,
  parseFrame,
  isCompressed,
  TYPE_REQUEST,
  TYPE_RESPONSE,
  TYPE_NOTIFY,
  FLAG_COMPRESSED,
} from "./frame.js";
import {
  FrameAssembler,
} from "./frame-assembler.js";
import { compressValue, decompressValue } from "./compress.js";

// ═══ Transport Interface (compatible with @modelcontextprotocol/sdk) ══════

/** Minimal transport interface matching MCP SDK's `Transport`. */
export interface Transport {
  start(): Promise<void>;
  send(message: JsonRpcMessage): Promise<void>;
  close(): Promise<void>;
  onmessage: ((message: JsonRpcMessage) => void) | null;
  onerror: ((error: Error) => void) | null;
  onclose: (() => void) | null;
}

/** JSON-RPC 2.0 message. */
export interface JsonRpcMessage {
  jsonrpc: "2.0";
  id?: string | number | null;
  method?: string;
  params?: Record<string, unknown>;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
}

// ═══ Options ════════════════════════════════════════════════════════════════

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

// ═══ Stdio Transport ════════════════════════════════════════════════════════

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
 *
 * const transport = new LumenStdioTransport({
 *   command: "npx",
 *   args: ["-y", "@anthropic/mcp-server-filesystem", "/tmp"],
 * });
 * await transport.start();
 * ```
 */
export class LumenStdioTransport implements Transport {
  private proc: ChildProcess | null = null;
  private rl: Interface | null = null;
  private useLumen = false;
  private assembler = new FrameAssembler();

  onmessage: ((message: JsonRpcMessage) => void) | null = null;
  onerror: ((error: Error) => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(private options: LumenStdioOptions) {}

  // ── Lifecycle ──────────────────────────────────────────────────────────

  async start(): Promise<void> {
    const opts = this.options;

    this.proc = spawn(opts.command, opts.args ?? [], {
      cwd: opts.cwd,
      env: { ...process.env, ...opts.env },
      stdio: ["pipe", "pipe", "pipe"],
    });

    this.proc.on("error", (err) => {
      this.onerror?.(err);
    });

    this.proc.on("exit", (code, signal) => {
      if (code !== 0) {
        this.onerror?.(
          new Error(`Server exited with code ${code}, signal ${signal}`),
        );
      }
      this.onclose?.();
    });

    // Stderr passthrough for debugging
    this.proc.stderr?.on("data", (chunk: Buffer) => {
      process.stderr.write(`[mcp-server stderr] ${chunk.toString()}`);
    });

    // Setup line reader for JSON-RPC path
    this.rl = createInterface({ input: this.proc.stdout! });

    // ── LUMEN negotiation ────────────────────────────────────────────
    if (!opts.forceJsonRpc) {
      const probe = buildProbe();
      this.proc.stdin!.write(probe);

      const negotiated = await this.waitForAck(
        opts.probeTimeoutMs ?? DEFAULT_PROBE_TIMEOUT_MS,
      );
      if (negotiated) {
        this.useLumen = true;
        // Switch to binary frame reader
        this.rl.close();
        this.startLumenReader();
        return;
      }
      // Fallback: server didn't ACK, but we already sent the probe bytes.
      // JSON-RPC servers will ignore them as garbage.
    }

    // ── JSON-RPC path ─────────────────────────────────────────────────
    this.rl.on("line", (line: string) => {
      try {
        const msg = JSON.parse(line) as JsonRpcMessage;
        this.onmessage?.(msg);
      } catch {
        // Ignore malformed lines (including binary probe garbage)
      }
    });
  }

  /** Wait for PROBE_ACK frame from stdout within timeout. */
  private waitForAck(timeoutMs: number): Promise<boolean> {
    return new Promise((resolve) => {
      const timer = setTimeout(() => resolve(false), timeoutMs);

      const onData = (chunk: Buffer) => {
        const frames = this.assembler.push(
          new Uint8Array(chunk.buffer, chunk.byteOffset, chunk.byteLength),
        );

        for (const frame of frames) {
          if (frame.frameType === 0x10 /* TYPE_PROBE_ACK */) {
            this.proc!.stdout!.removeListener("data", onData);
            clearTimeout(timer);
            const ack = parseAck(frame.payload);
            resolve(ack !== null);
            return;
          }
        }
      };

      this.proc!.stdout!.on("data", onData);
    });
  }

  /** After LUMEN negotiation, read binary frames from stdout. */
  private startLumenReader(): void {
    this.proc!.stdout!.on("data", (chunk: Buffer) => {
      const frames = this.assembler.push(
        new Uint8Array(chunk.buffer, chunk.byteOffset, chunk.byteLength),
      );

      for (const frame of frames) {
        let payload: Record<string, unknown>;
        if (isCompressed(frame)) {
          const val = decompressValue(frame.payload);
          payload = (val as Record<string, unknown>) ?? {};
        } else {
          try {
            payload = JSON.parse(
              new TextDecoder().decode(frame.payload),
            ) as Record<string, unknown>;
          } catch {
            continue;
          }
        }

        const msg: JsonRpcMessage = {
          jsonrpc: "2.0",
          ...payload,
        } as JsonRpcMessage;

        this.onmessage?.(msg);
      }
    });
  }

  // ── Send ──────────────────────────────────────────────────────────────

  async send(message: JsonRpcMessage): Promise<void> {
    if (!this.proc?.stdin) throw new Error("Transport not started");

    if (this.useLumen) {
      const frameType =
        message.id !== undefined && message.method
          ? TYPE_REQUEST
          : message.id !== undefined
            ? TYPE_RESPONSE
            : TYPE_NOTIFY;

      const payload = compressValue(
        message as unknown as Record<string, unknown>,
      );
      const total = buildSize(payload.length);
      const buf = new Uint8Array(total);
      buildFrame(frameType, FLAG_COMPRESSED, payload, buf, 0);
      this.proc.stdin.write(Buffer.from(buf));
    } else {
      const line = JSON.stringify(message) + "\n";
      this.proc.stdin.write(line);
    }
  }

  // ── Close ─────────────────────────────────────────────────────────────

  async close(): Promise<void> {
    this.rl?.close();
    this.proc?.stdin?.end();
    this.proc?.kill();
    this.onclose?.();
  }
}


// ═══ WebSocket Transport ════════════════════════════════════════════════════

export interface LumenWebSocketOptions extends LumenTransportOptions {
  /** Send binary WebSocket frames instead of text frames. */
  binaryFrames?: boolean;
}

/**
 * LUMEN over WebSocket (binary frames).
 *
 * Ideal for cloud gateways where the MCP server is behind a WebSocket
 * endpoint (e.g., Cadencia API Gateway → MCP servers).
 *
 * @example
 * ```typescript
 * import { WebSocket } from "ws";
 * import { LumenWebSocketTransport } from "@lumen/mcp-transport";
 *
 * const ws = new WebSocket("wss://api.cadencia.app/mcp");
 * const transport = new LumenWebSocketTransport(ws);
 * await transport.start();
 * ```
 */
export class LumenWebSocketTransport implements Transport {
  private useLumen = false;
  private wsReady = false;
  private assembler = new FrameAssembler();

  onmessage: ((message: JsonRpcMessage) => void) | null = null;
  onerror: ((error: Error) => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(
    private ws: WebSocketLike,
    private options: LumenWebSocketOptions = {},
  ) {}

  // ── Lifecycle ──────────────────────────────────────────────────────────

  async start(): Promise<void> {
    return new Promise((resolve, reject) => {
      // If the WebSocket is already open, negotiate immediately.
      if (
        this.ws.readyState === WebSocketReadyState.OPEN ||
        this.ws.readyState === 1
      ) {
        this.wsReady = true;
        this.negotiateAndSetup(resolve, reject);
        return;
      }

      // Otherwise, wait for the WebSocket to open.
      const originalOnOpen = this.ws.onopen;
      this.ws.onopen = (event: unknown) => {
        if (originalOnOpen) originalOnOpen.call(this.ws, event);
        this.wsReady = true;
        this.negotiateAndSetup(resolve, reject);
      };

      // Bubble errors
      const originalOnError = this.ws.onerror;
      this.ws.onerror = (error: Error) => {
        if (originalOnError) originalOnError.call(this.ws, error);
        this.onerror?.(error);
        reject(new Error("WebSocket connection failed"));
      };

      // Reject if the socket closes before opening
      const originalOnClose = this.ws.onclose;
      this.ws.onclose = (event: { code: number; reason: string }) => {
        if (originalOnClose) originalOnClose.call(this.ws, event);
        if (!this.wsReady) {
          reject(
            new Error(
              `WebSocket closed before negotiation: ${event.code} ${event.reason}`,
            ),
          );
        } else {
          this.onclose?.();
        }
      };
    });
  }

  private negotiateAndSetup(
    resolve: () => void,
    reject: (err: Error) => void,
  ): void {
    if (this.options.forceJsonRpc) {
      this.setupJsonRpcReader();
      resolve();
      return;
    }

    // Send LUMEN probe
    const probe = buildProbe();
    this.ws.send(probe);

    const timeout = this.options.probeTimeoutMs ?? DEFAULT_PROBE_TIMEOUT_MS;
    let negotiated = false;
    const timer = setTimeout(() => {
      if (!negotiated) {
        this.setupJsonRpcReader();
        resolve();
      }
    }, timeout);

    // Use FrameAssembler for robust ACK detection (handles
    // fragmented WebSocket messages where a frame spans multiple
    // onmessage calls).
    const ackAssembler = new FrameAssembler();

    this.ws.onmessage = (event: MessageEventLike) => {
      const data =
        typeof event.data === "string"
          ? new TextEncoder().encode(event.data)
          : event.data instanceof Uint8Array
            ? event.data
            : new Uint8Array(event.data as ArrayBuffer);

      const frames = ackAssembler.push(data);

      for (const frame of frames) {
        if (frame.frameType === 0x10 /* TYPE_PROBE_ACK */) {
          clearTimeout(timer);
          negotiated = true;
          this.useLumen = true;

          const ack = parseAck(frame.payload);
          if (!ack) {
            // ACK frame but malformed payload — treat as failed negotiation
            this.setupJsonRpcReader();
            resolve();
            return;
          }

          // Negotiation succeeded — switch to LUMEN reader.
          // Any leftover bytes in ackAssembler are discarded;
          // the server shouldn't send anything before the ACK.
          this.setupLumenReader();
          resolve();
        }
      }
    };
  }

  private setupJsonRpcReader(): void {
    this.ws.onmessage = (event: MessageEventLike) => {
      const text =
        typeof event.data === "string"
          ? event.data
          : new TextDecoder().decode(event.data as ArrayBuffer);
      try {
        const msg = JSON.parse(text) as JsonRpcMessage;
        this.onmessage?.(msg);
      } catch {
        // Ignore
      }
    };
  }

  private setupLumenReader(): void {
    this.ws.onmessage = (event: MessageEventLike) => {
      const raw =
        event.data instanceof Uint8Array
          ? new Uint8Array(
              event.data.buffer,
              event.data.byteOffset,
              event.data.byteLength,
            )
          : typeof event.data === "string"
            ? new TextEncoder().encode(event.data)
            : new Uint8Array(event.data as ArrayBuffer);

      const frames = this.assembler.push(raw);

      for (const frame of frames) {
        let payload: Record<string, unknown>;
        if (isCompressed(frame)) {
          const val = decompressValue(frame.payload);
          payload = (val as Record<string, unknown>) ?? {};
        } else {
          try {
            payload = JSON.parse(
              new TextDecoder().decode(frame.payload),
            ) as Record<string, unknown>;
          } catch {
            continue;
          }
        }

        const msg: JsonRpcMessage = {
          jsonrpc: "2.0",
          ...payload,
        } as JsonRpcMessage;

        this.onmessage?.(msg);
      }
    };
  }

  // ── Send ──────────────────────────────────────────────────────────────

  async send(message: JsonRpcMessage): Promise<void> {
    if (!this.wsReady) throw new Error("Transport not started");

    if (this.useLumen) {
      const frameType =
        message.id !== undefined && message.method
          ? TYPE_REQUEST
          : message.id !== undefined
            ? TYPE_RESPONSE
            : TYPE_NOTIFY;

      const payload = compressValue(
        message as unknown as Record<string, unknown>,
      );
      const total = buildSize(payload.length);
      const buf = new Uint8Array(total);
      buildFrame(frameType, FLAG_COMPRESSED, payload, buf, 0);
      this.ws.send(buf);
    } else {
      this.ws.send(JSON.stringify(message));
    }
  }

  // ── Close ─────────────────────────────────────────────────────────────

  async close(): Promise<void> {
    // Close the WebSocket if it's still open/connecting.
    if (
      this.ws.readyState === WebSocketReadyState.OPEN ||
      this.ws.readyState === WebSocketReadyState.CONNECTING ||
      this.ws.readyState === 1 ||
      this.ws.readyState === 0
    ) {
      this.ws.close(1000, "Transport closed");
    }
    this.wsReady = false;
    this.onclose?.();
  }
}

// ═══ WebSocket-like interface ═══════════════════════════════════════════════

export enum WebSocketReadyState {
  CONNECTING = 0,
  OPEN = 1,
  CLOSING = 2,
  CLOSED = 3,
}

export interface MessageEventLike {
  data: string | ArrayBuffer | Uint8Array;
}

export interface WebSocketLike {
  readyState: WebSocketReadyState | number;
  send(data: string | Uint8Array | ArrayBuffer): void;
  close(code?: number, reason?: string): void;
  onopen: ((event: unknown) => void) | null;
  onmessage: ((event: MessageEventLike) => void) | null;
  onerror: ((error: Error) => void) | null;
  onclose: ((event: { code: number; reason: string }) => void) | null;
}
