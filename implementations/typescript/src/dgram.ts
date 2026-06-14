/**
 * Datagram Transport — Level 3 UDP/multicast transport for LUMEN.
 *
 * Uses Node.js `dgram` module for UDP socket operations.
 * Each datagram carries exactly one complete LUMEN frame.
 *
 * ## Guarantees (none)
 * - No ordering — frames may arrive out of order
 * - No delivery — frames may be silently dropped
 * - No duplicate suppression
 *
 * ## Use cases
 * - Telemetry / metrics (fire-and-forget)
 * - Heartbeats (best-effort keep-alive)
 * - Log shipping (high throughput, loss-tolerant)
 * - Service discovery (multicast DISCOVER frames)
 */

import * as dgram from "node:dgram";
import {
  buildFrame,
  buildSize,
  parseFrame,
  type ParseResult,
} from "./frame.js";

// ═══ Constants ══════════════════════════════════════════════════════════════

/** Maximum UDP datagram payload (65535 − 8 UDP header − 20 IP header). */
export const MAX_DATAGRAM_SIZE = 65507;

/** Maximum LUMEN frame payload fitting in one datagram. */
export const MAX_FRAME_PAYLOAD = MAX_DATAGRAM_SIZE - 7; // Hyb128(5) + TYPE(1) + FLAGS(1)

/** Default multicast TTL. */
export const DEFAULT_MULTICAST_TTL = 1;

// ═══ DatagramTransport ══════════════════════════════════════════════════════

export interface DatagramTransportOptions {
  /** Address to bind to (default: "127.0.0.1"). */
  bindAddress?: string;
  /** Port to bind to (default: 0 = ephemeral). */
  bindPort?: number;
  /** Remote address for connected UDP. */
  remoteAddress?: string;
  /** Remote port for connected UDP. */
  remotePort?: number;
  /** Socket type: "udp4" or "udp6" (default: "udp4"). */
  type?: dgram.SocketType;
}

/**
 * A Level 3 datagram transport wrapping a Node.js UDP socket.
 *
 * @example
 * ```typescript
 * import { DatagramTransport, buildDgram } from "@lumen/mcp-transport";
 * import { TYPE_HEARTBEAT } from "@lumen/mcp-transport";
 *
 * // Receiver
 * const rx = new DatagramTransport({ bindPort: 9999 });
 * await rx.bind();
 * rx.onMessage = (data, rinfo) => {
 *   const frame = parseFrame(data);
 *   console.log(`Got ${frame?.payload.length} bytes from ${rinfo.address}`);
 * };
 *
 * // Sender
 * const tx = new DatagramTransport();
 * await tx.bind();
 * const frame = buildDgram(TYPE_HEARTBEAT, 0, Buffer.from("ping"));
 * tx.send(frame, 9999, "127.0.0.1");
 * ```
 */
export class DatagramTransport {
  private socket: dgram.Socket | null = null;
  private bindAddr: string;
  private bindPort: number;
  private remoteAddr: string | null;
  private remotePort: number | null;
  private socketType: dgram.SocketType;

  /** Callback invoked when a datagram is received. */
  onMessage: ((data: Buffer, rinfo: dgram.RemoteInfo) => void) | null = null;
  /** Callback for socket errors. */
  onError: ((err: Error) => void) | null = null;

  constructor(options: DatagramTransportOptions = {}) {
    this.bindAddr = options.bindAddress ?? "127.0.0.1";
    this.bindPort = options.bindPort ?? 0;
    this.remoteAddr = options.remoteAddress ?? null;
    this.remotePort = options.remotePort ?? null;
    this.socketType = options.type ?? "udp4";
  }

  // ── Lifecycle ──────────────────────────────────────────────────────

  /**
   * Create and bind the UDP socket.
   * Must be called before send/receive.
   */
  bind(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.socket = dgram.createSocket(this.socketType);

      this.socket.on("message", (data: Buffer, rinfo: dgram.RemoteInfo) => {
        if (this.onMessage) {
          this.onMessage(data, rinfo);
        }
      });

      this.socket.on("error", (err: Error) => {
        if (this.onError) {
          this.onError(err);
        }
      });

      this.socket.bind(this.bindPort, this.bindAddr, () => {
        resolve();
      });
    });
  }

  /**
   * Close the socket and release resources.
   */
  close(): Promise<void> {
    return new Promise((resolve) => {
      if (this.socket) {
        this.socket.close(() => {
          this.socket = null;
          resolve();
        });
      } else {
        resolve();
      }
    });
  }

  // ── Address ────────────────────────────────────────────────────────

  /** Get the bound local address. */
  address(): { address: string; family: string; port: number } | null {
    return this.socket?.address() ?? null;
  }

  // ── Send ───────────────────────────────────────────────────────────

  /**
   * Send a raw LUMEN frame buffer to a destination.
   *
   * @param data - Raw frame bytes (Hyb128 + TYPE + FLAGS + payload).
   * @param port - Destination port.
   * @param address - Destination address (default: "127.0.0.1").
   */
  send(
    data: Buffer | Uint8Array,
    port: number,
    address: string = "127.0.0.1",
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!this.socket) {
        return reject(new Error("Socket not bound — call bind() first"));
      }
      const buf = Buffer.isBuffer(data) ? data : Buffer.from(data);
      const len = Math.min(buf.length, MAX_DATAGRAM_SIZE);
      this.socket.send(buf.subarray(0, len), port, address, (err) => {
        if (err) reject(err);
        else resolve();
      });
    });
  }

  /**
   * Send to the connected peer (requires remoteAddress/remotePort in options).
   */
  sendConnected(data: Buffer | Uint8Array): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!this.socket) {
        return reject(new Error("Socket not bound — call bind() first"));
      }
      if (!this.remotePort) {
        return reject(new Error("No remote port configured for connected send"));
      }
      const addr = this.remoteAddr ?? "127.0.0.1";
      const buf = Buffer.isBuffer(data) ? data : Buffer.from(data);
      const len = Math.min(buf.length, MAX_DATAGRAM_SIZE);
      this.socket.send(buf.subarray(0, len), this.remotePort, addr, (err) => {
        if (err) reject(err);
        else resolve();
      });
    });
  }

  // ── Multicast ──────────────────────────────────────────────────────

  /**
   * Join a multicast group.
   *
   * @param multicastAddress - e.g. "239.1.1.1"
   * @param interfaceAddress - Local interface address (optional).
   */
  addMulticastMembership(
    multicastAddress: string,
    interfaceAddress?: string,
  ): void {
    if (!this.socket) {
      throw new Error("Socket not bound — call bind() first");
    }
    this.socket.addMembership(multicastAddress, interfaceAddress);
  }

  /**
   * Leave a multicast group.
   */
  dropMulticastMembership(
    multicastAddress: string,
    interfaceAddress?: string,
  ): void {
    if (!this.socket) {
      throw new Error("Socket not bound — call bind() first");
    }
    this.socket.dropMembership(multicastAddress, interfaceAddress);
  }

  /**
   * Set the multicast TTL (time-to-live / hop limit).
   *
   * - 0: same host
   * - 1: same subnet (default)
   * - 32: same site
   * - 64: same region
   * - 128: same continent
   * - 255: unrestricted
   */
  setMulticastTTL(ttl: number): void {
    if (!this.socket) {
      throw new Error("Socket not bound — call bind() first");
    }
    this.socket.setMulticastTTL(ttl);
  }

  /**
   * Enable or disable multicast loopback (default: enabled).
   * When enabled, the host receives its own multicast sends.
   */
  setMulticastLoopback(flag: boolean): void {
    if (!this.socket) {
      throw new Error("Socket not bound — call bind() first");
    }
    this.socket.setMulticastLoopback(flag);
  }

  // ── Broadcast ──────────────────────────────────────────────────────

  /**
   * Enable or disable broadcast (default: disabled).
   */
  setBroadcast(flag: boolean): void {
    if (!this.socket) {
      throw new Error("Socket not bound — call bind() first");
    }
    this.socket.setBroadcast(flag);
  }

  // ── Buffer size ────────────────────────────────────────────────────

  /**
   * Get the socket's receive buffer size.
   */
  getRecvBufferSize(): number {
    if (!this.socket) {
      throw new Error("Socket not bound — call bind() first");
    }
    return this.socket.getRecvBufferSize();
  }

  /**
   * Set the socket's receive buffer size.
   */
  setRecvBufferSize(size: number): void {
    if (!this.socket) {
      throw new Error("Socket not bound — call bind() first");
    }
    this.socket.setRecvBufferSize(size);
  }
}

// ═══ Convenience builders ═══════════════════════════════════════════════════

/**
 * Build a complete LUMEN frame for datagram transmission.
 *
 * Returns a Buffer with `[Hyb128_LEN][TYPE][FLAGS][PAYLOAD]`.
 * Throws if payload exceeds `MAX_FRAME_PAYLOAD`.
 */
export function buildDgram(
  frameType: number,
  flags: number,
  payload: Buffer | Uint8Array,
): Buffer {
  if (payload.length > MAX_FRAME_PAYLOAD) {
    throw new Error(
      `Datagram payload ${payload.length} exceeds max ${MAX_FRAME_PAYLOAD}`,
    );
  }
  const total = buildSize(payload.length);
  const buf = Buffer.alloc(total);
  buildFrame(frameType, flags, payload, buf);
  return buf;
}

/**
 * Parse a received datagram buffer into a LUMEN frame.
 * Returns null if the data is not a valid frame.
 */
export function parseDgram(data: Buffer | Uint8Array): ParseResult {
  return parseFrame(
    Buffer.isBuffer(data) ? data : Buffer.from(data),
  );
}
