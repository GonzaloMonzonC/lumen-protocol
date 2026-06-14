/**
 * LUMEN Level 2 — Shared Memory FFI Integration Tests
 *
 * Tests the ShmTransportFFI class end-to-end using the native Rust
 * lumen.dll via koffi FFI.
 *
 * Run with: node --test dist/shm_ffi.test.js
 *           (after: npm run build && cd ../rust && cargo build --release)
 */

import { before, describe, it, afterEach } from "node:test";
import * as assert from "node:assert";

let ShmTransportFFI: typeof import("./shm_ffi.js").ShmTransportFFI;
let DEFAULT_SHM_SIZE: number;

let transports: Array<{ close(): void }> = [];

function uniqueName(): string {
  return "/lumen-test-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);
}

// Clean up transports after each test
afterEach(() => {
  for (const t of transports) {
    try { t.close(); } catch { /* best effort */ }
  }
  transports = [];
});

// ═══ Setup ═════════════════════════════════════════════════════════════

before(async () => {
  const mod = await import("./shm_ffi.js");
  ShmTransportFFI = mod.ShmTransportFFI;
  DEFAULT_SHM_SIZE = mod.DEFAULT_SHM_SIZE;
});

// ═══ Helpers ═══════════════════════════════════════════════════════════

function createServer(name: string) {
  const s = ShmTransportFFI.createServer(name);
  transports.push(s);
  return s;
}

function openClient(name: string) {
  const c = ShmTransportFFI.openClient(name);
  transports.push(c);
  return c;
}

// ═══ Tests ═════════════════════════════════════════════════════════════

describe("ShmTransportFFI", () => {

  it("creates and opens a shared memory region", () => {
    const name = uniqueName();
    const server = createServer(name);
    assert.ok(server, "server handle should be non-null");

    const client = openClient(name);
    assert.ok(client, "client handle should be non-null");
  });

  it("roundtrip: client → server (Ring A)", () => {
    const name = uniqueName();
    const server = createServer(name);
    const client = openClient(name);

    const payload = Buffer.from("hello from client!");
    client.writeFrame(payload);

    const received = server.readFrame();
    assert.ok(received !== null, "server should receive frame");
    assert.deepStrictEqual(received, payload);
  });

  it("roundtrip: server → client (Ring B)", () => {
    const name = uniqueName();
    const server = createServer(name);
    const client = openClient(name);

    const payload = Buffer.from("hello from server!");
    server.writeFrame(payload);

    const received = client.readFrame();
    assert.ok(received !== null, "client should receive frame");
    assert.deepStrictEqual(received, payload);
  });

  it("bidirectional echo: client→server→client", () => {
    const name = uniqueName();
    const server = createServer(name);
    const client = openClient(name);

    // Client sends
    const msg = Buffer.from("echo me");
    client.writeFrame(msg);

    // Server receives and echoes back
    const req = server.readFrame();
    assert.ok(req !== null, "server should receive");
    assert.deepStrictEqual(req, msg);
    server.writeFrame(req!);

    // Client receives echo
    const echo = client.readFrame();
    assert.ok(echo !== null, "client should receive echo");
    assert.deepStrictEqual(echo, msg);
  });

  it("handles multiple frames in sequence", () => {
    const name = uniqueName();
    const server = createServer(name);
    const client = openClient(name);

    const messages = [
      Buffer.from("msg1"),
      Buffer.from("msg2"),
      Buffer.from("msg3"),
    ];

    for (const msg of messages) {
      client.writeFrame(msg);
    }

    for (const msg of messages) {
      const received = server.readFrame();
      assert.ok(received !== null, "server should receive each frame");
      assert.deepStrictEqual(received, msg);
    }

    // No more frames
    const empty = server.readFrame();
    assert.strictEqual(empty, null, "should return null when empty");
  });

  it("handles binary payload (non-UTF8)", () => {
    const name = uniqueName();
    const server = createServer(name);
    const client = openClient(name);

    const payload = Buffer.allocUnsafe(256);
    for (let i = 0; i < 256; i++) {
      payload[i] = i;
    }

    client.writeFrame(payload);
    const received = server.readFrame(1024);
    assert.ok(received !== null);
    assert.strictEqual(received!.length, 256);
    assert.ok(received!.equals(payload));
  });

  it("handles empty payload", () => {
    const name = uniqueName();
    const server = createServer(name);
    const client = openClient(name);

    const payload = Buffer.alloc(0);
    client.writeFrame(payload);

    const received = server.readFrame();
    assert.ok(received !== null, "should receive empty frame");
    assert.strictEqual(received!.length, 0);
  });

  it("readFrame returns null when no data", () => {
    const name = uniqueName();
    const server = createServer(name);
    const client = openClient(name);

    const empty = server.readFrame();
    assert.strictEqual(empty, null);
    const empty2 = client.readFrame();
    assert.strictEqual(empty2, null);
  });

  it("handles large payload (64 KB)", () => {
    const name = uniqueName();
    const server = createServer(name);
    const client = openClient(name);

    const payload = Buffer.allocUnsafe(65536);
    for (let i = 0; i < 65536; i++) {
      payload[i] = (i & 0xFF);
    }

    client.writeFrame(payload);
    const received = server.readFrame(65536 + 4);
    assert.ok(received !== null);
    assert.strictEqual(received!.length, 65536);
    assert.strictEqual(received![0], 0);
    assert.strictEqual(received![65535], 255);
  });

  it("close is idempotent", () => {
    const name = uniqueName();
    const server = ShmTransportFFI.createServer(name);
    server.close();
    // Should not throw
    server.close();

    // Create another with same name — should work after close+unlink
    const server2 = ShmTransportFFI.createServer(name);
    server2.close();
  });
});
