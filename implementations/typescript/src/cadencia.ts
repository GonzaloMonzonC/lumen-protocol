/**
 * Cadencia Bridge Client — spawns the Rust `cadencia-bridge` sidecar
 * and communicates via line-delimited JSON on stdin/stdout.
 *
 * This is how the VS Code extension (TypeScript) offloads heavy
 * I/O and LUMEN encoding to a native Rust process.
 *
 * Protocol (see cadencia-bridge.rs for the Rust side):
 * ```
 * TS → Rust:  {"cmd":"index","files":["path1","path2",...]}
 * Rust → TS:  {"status":"ok","files":1234,"total_bytes":...}
 * ```
 */

import { spawn, ChildProcess } from "child_process";
import { createInterface } from "readline";

// ── Types ────────────────────────────────────────────────────────────────────

export interface BridgeCommand {
  cmd: "ping" | "index" | "stop";
  files?: string[];
  id?: number;
}

export interface BridgeResponse {
  status: "ok" | "error";
  version?: string;
  protocol?: string;
  files?: number;
  total_bytes?: number;
  wire_bytes?: number;
  encode_us?: number;
  elapsed_us?: number;
  error?: string;
  reason?: string;
  id?: number;
}

export interface BridgeOptions {
  /** Path to the cadencia-bridge binary. */
  binaryPath: string;
  /** Working directory for file resolution. */
  cwd?: string;
  /** Called when the bridge process exits unexpectedly. */
  onCrash?: (code: number | null) => void;
}

// ── Client ───────────────────────────────────────────────────────────────────

export class CadenciaBridge {
  private proc: ChildProcess | null = null;
  private pending: Map<
    number,
    { resolve: (r: BridgeResponse) => void; reject: (e: Error) => void }
  > = new Map();
  private seq = 0;

  constructor(private options: BridgeOptions) {}

  /** Start the sidecar process. Returns the ready response. */
  async start(): Promise<BridgeResponse> {
    this.proc = spawn(this.options.binaryPath, [], {
      cwd: this.options.cwd,
      stdio: ["pipe", "pipe", "pipe"],
    });

    const rl = createInterface({ input: this.proc.stdout! });
    rl.on("line", (line: string) => {
      try {
        const msg: BridgeResponse = JSON.parse(line);
        // Match response to its pending request by sequence id
        if (msg.id !== undefined && this.pending.has(msg.id)) {
          const { resolve } = this.pending.get(msg.id)!;
          this.pending.delete(msg.id);
          resolve(msg);
        } else {
          // Unsolicited response — log and drop
          console.warn(
            `CadenciaBridge: unsolicited response (id=${msg.id ?? "none"})`
          );
        }
      } catch {
        // ignore malformed lines
      }
    });

    this.proc.on("exit", (code) => {
      this.options.onCrash?.(code);
      // Reject all pending
      for (const [, { reject }] of this.pending) {
        reject(new Error(`Bridge exited with code ${code}`));
      }
      this.pending.clear();
    });

    // The bridge sends a ready signal immediately on start
    return this.send({ cmd: "ping" });
  }

  /** Index a list of files. Returns timing and wire stats. */
  async index(files: string[]): Promise<BridgeResponse> {
    return this.send({ cmd: "index", files });
  }

  /** Stop the sidecar gracefully. */
  async stop(): Promise<void> {
    try {
      await this.send({ cmd: "stop" });
    } finally {
      this.proc?.kill();
    }
  }

  private send(cmd: BridgeCommand): Promise<BridgeResponse> {
    return new Promise((resolve, reject) => {
      if (!this.proc || !this.proc.stdin) {
        reject(new Error("Bridge not started"));
        return;
      }
      const seq = ++this.seq;
      this.pending.set(seq, { resolve, reject });
      const wire = { ...cmd, id: seq };
      this.proc.stdin.write(JSON.stringify(wire) + "\n");

      // Timeout after 30s
      setTimeout(() => {
        if (this.pending.has(seq)) {
          this.pending.delete(seq);
          reject(new Error("Bridge request timed out"));
        }
      }, 30_000);
    });
  }
}
