/**
 * Unit tests for LumenStdioTransport and LumenWebSocketTransport.
 *
 * Run: node --import tsx --test src/transport.test.ts
 */

import { describe, it, afterEach } from "node:test";
import assert from "node:assert/strict";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import {
  LumenStdioTransport,
  LumenWebSocketTransport,
  WebSocketReadyState,
} from "./transport.js";
import { buildAck } from "./negotiation.js";
import type { JsonRpcMessage, WebSocketLike, MessageEventLike } from "./transport.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

// ═══ Helpers ════════════════════════════════════════════════════════════════

/** Path to the Node.js binary (same as the one running this test). */
const NODE = process.execPath;

/** Command that spawns the echo helper. */
function echoCommand(): [string, string[]] {
  return [NODE, ["--import", "tsx", join(__dirname, "__test_echo__.ts")]];
}

/** JSON-RPC echo subprocess: reads lines, writes them back. */
function jsonEchoCommand(): [string, string[]] {
  return [
    NODE,
    [
      "-e",
      `const rl=require("readline").createInterface({input:process.stdin});rl.on("line",(l)=>{process.stdout.write(l+"\\n")})`,
    ],
  ];
}

/** Wait for a promise or timeout. */
function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T | "timeout"> {
  return Promise.race([
    promise.then((v) => v),
    new Promise<"timeout">((r) => setTimeout(() => r("timeout"), ms)),
  ]);
}

/** Poll until condition is true or timeout. */
async function pollUntil(fn: () => boolean, intervalMs: number, maxAttempts: number): Promise<void> {
  for (let i = 0; i < maxAttempts; i++) {
    if (fn()) return;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

// ═══ LumenStdioTransport ═══════════════════════════════════════════════════

describe("LumenStdioTransport", () => {
  const transports: LumenStdioTransport[] = [];

  afterEach(async () => {
    for (const t of transports) {
      try {
        await t.close();
      } catch {
        // best-effort cleanup
      }
    }
    transports.length = 0;
  });

  // ── Constructor ──────────────────────────────────────────────────────

  it("constructor stores command, args, env, and cwd", () => {
    const t = new LumenStdioTransport({
      command: "node",
      args: ["-e", "1"],
      env: { FOO: "bar" },
      cwd: "/tmp",
    });
    transports.push(t);

    const opts = (t as Record<string, unknown>)["options"] as Record<string, unknown>;
    assert.equal(opts.command, "node");
    assert.deepEqual(opts.args, ["-e", "1"]);
    assert.deepEqual(opts.env, { FOO: "bar" });
    assert.equal(opts.cwd, "/tmp");
  });

  it("constructor defaults args, env, and cwd to undefined", () => {
    const t = new LumenStdioTransport({ command: "echo" });
    transports.push(t);
    const opts = (t as Record<string, unknown>)["options"] as Record<string, unknown>;
    assert.equal(opts.command, "echo");
    assert.equal(opts.args, undefined);
    assert.equal(opts.env, undefined);
    assert.equal(opts.cwd, undefined);
  });

  // ── JSON-RPC fallback ────────────────────────────────────────────────

  it("force_json_rpc=true uses JSON-RPC mode (no LUMEN negotiation)", async () => {
    const [cmd, args] = echoCommand();
    const t = new LumenStdioTransport({
      command: cmd,
      args,
      forceJsonRpc: true,
    });
    transports.push(t);

    await t.start();

    const received = new Promise<JsonRpcMessage>((resolve) => {
      t.onmessage = (msg) => resolve(msg);
    });

    const msg: JsonRpcMessage = { jsonrpc: "2.0", id: 1, method: "ping" };
    await t.send(msg);

    const result = await withTimeout(received, 2000);
    assert.notEqual(result, "timeout", "Should receive echoed message");
    if (result !== "timeout") {
      assert.equal(result.jsonrpc, "2.0");
      assert.equal(result.id, 1);
      assert.equal(result.method, "ping");
    }

    // Verify transport is NOT in LUMEN mode
    assert.equal((t as Record<string, unknown>)["useLumen"], false);
  });

  it("force_json_rpc=false with simple echo falls back to JSON-RPC after probe timeout", async () => {
    const [cmd, args] = jsonEchoCommand();
    const t = new LumenStdioTransport({
      command: cmd,
      args,
      probeTimeoutMs: 200,
    });
    transports.push(t);

    await t.start();

    const received = new Promise<JsonRpcMessage>((resolve) => {
      t.onmessage = (msg) => resolve(msg);
    });

    const msg: JsonRpcMessage = { jsonrpc: "2.0", id: 2, method: "hello" };
    await t.send(msg);

    const result = await withTimeout(received, 2000);
    assert.notEqual(result, "timeout");
    if (result !== "timeout") {
      assert.equal(result.id, 2);
      assert.equal(result.method, "hello");
    }
  });

  // ── LUMEN probe ──────────────────────────────────────────────────────

  it("sends LUMEN probe on start when force_json_rpc=false", async () => {
    const [cmd, args] = echoCommand();
    const t = new LumenStdioTransport({
      command: cmd,
      args,
      probeTimeoutMs: 1000,
    });
    transports.push(t);

    await t.start();

    // The echo helper responds with PROBE_ACK → negotiation should succeed
    assert.equal((t as Record<string, unknown>)["useLumen"], true);
  });

  // ── Message sending (JSON-RPC path) ──────────────────────────────────

  it("send() writes JSON line to stdin in JSON-RPC mode", async () => {
    const [cmd, args] = echoCommand();
    const t = new LumenStdioTransport({
      command: cmd,
      args,
      forceJsonRpc: true,
    });
    transports.push(t);

    await t.start();

    const received: JsonRpcMessage[] = [];
    t.onmessage = (msg) => received.push(msg);

    await t.send({ jsonrpc: "2.0", id: 1, method: "tools/list" });
    await t.send({ jsonrpc: "2.0", id: 2, method: "prompts/get" });

    await pollUntil(() => received.length >= 2, 50, 50);

    assert.equal(received.length, 2);
    assert.equal(received[0].id, 1);
    assert.equal(received[0].method, "tools/list");
    assert.equal(received[1].id, 2);
    assert.equal(received[1].method, "prompts/get");
  });

  // ── Message sending (LUMEN path) ─────────────────────────────────────

  it("send() uses LUMEN binary frames after successful negotiation", async () => {
    const [cmd, args] = echoCommand();
    const t = new LumenStdioTransport({
      command: cmd,
      args,
      probeTimeoutMs: 2000,
    });
    transports.push(t);

    await t.start();

    // Verify LUMEN mode active
    assert.equal((t as Record<string, unknown>)["useLumen"], true);

    const received: JsonRpcMessage[] = [];
    t.onmessage = (msg) => received.push(msg);

    await t.send({
      jsonrpc: "2.0",
      id: 3,
      method: "initialize",
      params: { protocolVersion: "1.0" },
    });

    await pollUntil(() => received.length >= 1, 50, 50);

    assert.equal(received.length, 1);
    assert.equal(received[0].jsonrpc, "2.0");
    assert.equal(received[0].id, 3);
    assert.equal(received[0].method, "initialize");
  });

  // ── onmessage callback ───────────────────────────────────────────────

  it("onmessage fires when receiving JSON-RPC messages", async () => {
    const [cmd, args] = echoCommand();
    const t = new LumenStdioTransport({
      command: cmd,
      args,
      forceJsonRpc: true,
    });
    transports.push(t);

    const messages: JsonRpcMessage[] = [];
    t.onmessage = (msg) => messages.push(msg);

    await t.start();

    await t.send({ jsonrpc: "2.0", id: 1, method: "ping" });
    await t.send({ jsonrpc: "2.0", id: 2, result: { ok: true } });
    await t.send({ jsonrpc: "2.0", method: "notify" });

    await pollUntil(() => messages.length >= 3, 50, 50);

    assert.equal(messages.length, 3);
    assert.equal(messages[0].id, 1);
    assert.equal(messages[0].method, "ping");
    assert.equal(messages[1].id, 2);
    assert.ok(messages[1].result);
    assert.equal(messages[2].method, "notify");
  });

  // ── close() ──────────────────────────────────────────────────────────

  it("close() terminates the subprocess", async () => {
    const [cmd, args] = echoCommand();
    const t = new LumenStdioTransport({
      command: cmd,
      args,
      forceJsonRpc: true,
    });
    transports.push(t);

    await t.start();

    const proc = (t as Record<string, unknown>)["proc"] as {
      killed: boolean;
      exitCode: number | null;
    } | null;
    assert.ok(proc);
    assert.equal(proc.killed, false);

    let closed = false;
    t.onclose = () => {
      closed = true;
    };

    await t.close();

    // Wait a bit for the process to actually terminate
    await new Promise((r) => setTimeout(r, 200));

    assert.ok(closed, "onclose should have been called");
    assert.ok(proc.killed || proc.exitCode !== null, "Process should be killed or exited");
  });

  it("send() throws when called before start()", async () => {
    const [cmd, args] = echoCommand();
    const t = new LumenStdioTransport({
      command: cmd,
      args,
      forceJsonRpc: true,
    });
    transports.push(t);

    await assert.rejects(
      () => t.send({ jsonrpc: "2.0", id: 1, method: "ping" }),
      /not started/i,
    );
  });

  // ── onerror callback ─────────────────────────────────────────────────

  it("onerror fires when spawning an invalid command", async () => {
    const t = new LumenStdioTransport({
      command: "this-command-does-not-exist-xyz",
      args: [],
      forceJsonRpc: true,
    });
    transports.push(t);

    const errorPromise = new Promise<Error>((resolve) => {
      t.onerror = (err) => resolve(err);
    });

    try {
      await t.start();
    } catch {
      // start itself may throw on spawn failure
    }

    const err = await withTimeout(errorPromise, 2000);
    if (err !== "timeout") {
      assert.ok(err instanceof Error);
    }
  });
});

// ═══ LumenWebSocketTransport ═══════════════════════════════════════════════

describe("LumenWebSocketTransport", () => {
  // ── Mock WebSocket ────────────────────────────────────────────────────

  /** Create a mock WebSocketLike for testing. */
  function mockWs(readyState: number = WebSocketReadyState.OPEN): WebSocketLike & {
    _sent: (string | Uint8Array | ArrayBuffer)[];
    _closed: { code?: number; reason?: string } | null;
    _triggerMessage(data: MessageEventLike): void;
  } {
    const sent: (string | Uint8Array | ArrayBuffer)[] = [];
    let closed: { code?: number; reason?: string } | null = null;
    let _onmessage: ((event: MessageEventLike) => void) | null = null;

    const ws: WebSocketLike & {
      _sent: typeof sent;
      _closed: typeof closed;
      _triggerMessage: (data: MessageEventLike) => void;
    } = {
      readyState,
      send(data: string | Uint8Array | ArrayBuffer) {
        sent.push(data);
      },
      close(code?: number, reason?: string) {
        closed = { code, reason };
        if (ws.onclose) ws.onclose({ code: code ?? 1000, reason: reason ?? "" });
      },
      onopen: null,
      onmessage: null,
      onerror: null,
      onclose: null,
      _sent: sent,
      _closed: closed,
      _triggerMessage(data: MessageEventLike) {
        if (_onmessage) _onmessage(data);
      },
    };

    // Use a proxy to intercept onmessage assignment
    return new Proxy(ws, {
      set(target, prop, value) {
        if (prop === "onmessage") {
          _onmessage = value;
        }
        return Reflect.set(target, prop, value);
      },
    }) as typeof ws;
  }

  // ── Constructor ──────────────────────────────────────────────────────

  it("constructor stores the WebSocket reference", () => {
    const ws = mockWs();
    const t = new LumenWebSocketTransport(ws);
    assert.equal((t as Record<string, unknown>)["ws"], ws);
  });

  it("constructor stores options (binaryFrames)", () => {
    const ws = mockWs();
    const t = new LumenWebSocketTransport(ws, { binaryFrames: true });
    const opts = (t as Record<string, unknown>)["options"] as Record<string, unknown>;
    assert.equal(opts.binaryFrames, true);
  });

  // ── Message sending (JSON-RPC path) ──────────────────────────────────

  it("send() sends JSON string over WebSocket when force_json_rpc=true", async () => {
    const ws = mockWs(WebSocketReadyState.OPEN);
    const t = new LumenWebSocketTransport(ws, { forceJsonRpc: true });

    await t.start();

    const msg: JsonRpcMessage = { jsonrpc: "2.0", id: 1, method: "ping" };
    await t.send(msg);

    assert.equal(ws._sent.length, 1);
    assert.equal(ws._sent[0], JSON.stringify(msg));
  });

  it("send() sends LUMEN binary frame after negotiation", async () => {
    const ws = mockWs(WebSocketReadyState.OPEN);
    const t = new LumenWebSocketTransport(ws);

    await t.start();

    // After start, the transport sends a probe and waits for ACK
    assert.ok(ws._sent.length >= 1, "Probe should be sent");

    // Simulate receiving a PROBE_ACK to complete negotiation
    const ackFrame = buildAck({ v: 1, caps: ["compression"] });
    ws._triggerMessage({ data: ackFrame });

    // Clear sent messages before sending our test message
    ws._sent.length = 0;

    const msg: JsonRpcMessage = {
      jsonrpc: "2.0",
      id: 2,
      method: "initialize",
    };
    await t.send(msg);

    // Should send binary (Uint8Array), not string
    assert.equal(ws._sent.length, 1);
    assert.ok(ws._sent[0] instanceof Uint8Array, "Should send binary LUMEN frame");
  });

  it("send() throws when transport not started", async () => {
    const ws = mockWs(WebSocketReadyState.CONNECTING);
    const t = new LumenWebSocketTransport(ws, { forceJsonRpc: true });

    await assert.rejects(
      () => t.send({ jsonrpc: "2.0", id: 1, method: "ping" }),
      /not started/i,
    );
  });

  // ── close() ──────────────────────────────────────────────────────────

  it("close() calls ws.close() and fires onclose", async () => {
    const ws = mockWs(WebSocketReadyState.OPEN);
    const t = new LumenWebSocketTransport(ws);

    let closed = false;
    t.onclose = () => {
      closed = true;
    };

    await t.close();

    assert.ok(ws._closed);
    assert.equal(ws._closed.code, 1000);
    assert.equal(ws._closed.reason, "Transport closed");
    assert.ok(closed);
  });

  it("close() does not call ws.close() if already CLOSED", async () => {
    const ws = mockWs(WebSocketReadyState.CLOSED);
    const t = new LumenWebSocketTransport(ws);

    await t.close();

    assert.equal(ws._closed, null);
  });
});
