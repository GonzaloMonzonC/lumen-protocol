/**
 * Tests for Level 3 Datagram Transport (TypeScript).
 *
 * Run: `npx tsc && node --test dist/dgram.test.js`
 */

import * as assert from "node:assert/strict";
import { describe, it, afterEach } from "node:test";
import {
  DatagramTransport,
  buildDgram,
  parseDgram,
  MAX_FRAME_PAYLOAD,
  MAX_DATAGRAM_SIZE,
} from "./dgram.js";
import {
  TYPE_HEARTBEAT,
  TYPE_NOTIFY,
} from "./frame.js";

describe("DatagramTransport", () => {
  const transports: DatagramTransport[] = [];

  afterEach(async () => {
    for (const t of transports.splice(0)) {
      try {
        await t.close();
      } catch {
        // ignore close errors in cleanup
      }
    }
  });

  function makeTx(options?: ConstructorParameters<typeof DatagramTransport>[0]): DatagramTransport {
    const t = new DatagramTransport(options);
    transports.push(t);
    return t;
  }

  function makeRx(options?: ConstructorParameters<typeof DatagramTransport>[0]): DatagramTransport {
    const t = new DatagramTransport(options);
    transports.push(t);
    return t;
  }

  // ── bind / address ─────────────────────────────────────────────

  it("binds and returns local address", async () => {
    const t = makeRx({ bindPort: 0 });
    await t.bind();
    const addr = t.address();
    assert.ok(addr);
    assert.equal(addr.family, "IPv4");
    assert.ok(addr.port > 0);
  });

  it("binds on specified port", async () => {
    const t = makeRx({ bindPort: 9998 });
    await t.bind();
    const addr = t.address();
    assert.ok(addr);
    assert.equal(addr.port, 9998);
  });

  // ── send / receive unicast ──────────────────────────────────────

  it("sends and receives a datagram", async () => {
    const rx = makeRx();
    await rx.bind();
    const rxAddr = rx.address()!;

    const tx = makeTx();
    await tx.bind();

    const payload = Buffer.from("hello datagram");
    const frame = buildDgram(TYPE_HEARTBEAT, 0, payload);

    const received = new Promise<Buffer>((resolve) => {
      rx.onMessage = (data) => resolve(data);
    });

    await tx.send(frame, rxAddr.port, "127.0.0.1");

    const data = await received;
    assert.deepEqual(data, frame);
  });

  it("receives multiple datagrams", async () => {
    const rx = makeRx();
    await rx.bind();
    const rxAddr = rx.address()!;

    const tx = makeTx();
    await tx.bind();

    const frames = Array.from({ length: 5 }, (_, i) =>
      buildDgram(TYPE_NOTIFY, 0, Buffer.from(`msg${i}`)),
    );

    const received: Buffer[] = [];
    rx.onMessage = (data) => received.push(data);

    for (const f of frames) {
      await tx.send(f, rxAddr.port, "127.0.0.1");
    }

    // Wait for all to arrive
    await new Promise((resolve) => setTimeout(resolve, 50));

    assert.equal(received.length, frames.length);
    for (let i = 0; i < frames.length; i++) {
      assert.deepEqual(received[i], frames[i]);
    }
  });

  it("parsed frame has correct type and payload", async () => {
    const rx = makeRx();
    await rx.bind();
    const rxAddr = rx.address()!;

    const tx = makeTx();
    await tx.bind();

    const payload = Buffer.from("parse me");
    const frame = buildDgram(TYPE_HEARTBEAT, 0, payload);

    const received = new Promise<Buffer>((resolve) => {
      rx.onMessage = (data) => resolve(data);
    });

    await tx.send(frame, rxAddr.port, "127.0.0.1");

    const data = await received;
    const result = parseDgram(data);
    assert.equal(result.kind, "complete");
    if (result.kind === "complete") {
      assert.equal(result.frame.frameType, TYPE_HEARTBEAT);
      assert.deepEqual(result.frame.payload, payload);
    }
  });

  // ── Close ───────────────────────────────────────────────────────

  it("close releases the socket", async () => {
    const t = makeRx();
    await t.bind();
    assert.ok(t.address());
    await t.close();
    assert.equal(t.address(), null);
  });

  it("close is idempotent", async () => {
    const t = makeRx();
    await t.bind();
    await t.close();
    await t.close(); // should not throw
  });

  it("send after close rejects", async () => {
    const t = makeRx();
    await t.bind();
    await t.close();

    const frame = buildDgram(TYPE_HEARTBEAT, 0, Buffer.from("x"));
    await assert.rejects(
      () => t.send(frame, 9999, "127.0.0.1"),
      /Socket not bound/,
    );
  });

  // ── buildDgram / parseDgram ─────────────────────────────────────

  it("buildDgram creates valid frame", () => {
    const payload = Buffer.from("test");
    const frame = buildDgram(TYPE_NOTIFY, 0, payload);
    assert.ok(frame.length > payload.length + 2); // Hyb128 + TYPE + FLAGS + payload

    const result = parseDgram(frame);
    assert.equal(result.kind, "complete");
    if (result.kind === "complete") {
      assert.equal(result.frame.frameType, TYPE_NOTIFY);
      assert.deepEqual(result.frame.payload, payload);
    }
  });

  it("buildDgram rejects payload exceeding max", () => {
    const tooBig = Buffer.alloc(MAX_FRAME_PAYLOAD + 1);
    assert.throws(
      () => buildDgram(TYPE_NOTIFY, 0, tooBig),
      /exceeds max/,
    );
  });

  it("buildDgram handles max payload exactly", () => {
    const maxPayload = Buffer.alloc(MAX_FRAME_PAYLOAD, 0x42);
    const frame = buildDgram(TYPE_NOTIFY, 0, maxPayload);
    assert.ok(frame.length <= MAX_DATAGRAM_SIZE);
    assert.ok(frame.length > MAX_FRAME_PAYLOAD);

    const result = parseDgram(frame);
    assert.equal(result.kind, "complete");
    if (result.kind === "complete") {
      assert.equal(result.frame.payload.length, MAX_FRAME_PAYLOAD);
    }
  });

  // ── empty payload ───────────────────────────────────────────────

  it("buildDgram handles empty payload", () => {
    const frame = buildDgram(TYPE_HEARTBEAT, 0, Buffer.alloc(0));
    assert.ok(frame.length >= 3); // Hyb128(1) + TYPE + FLAGS

    const result = parseDgram(frame);
    assert.equal(result.kind, "complete");
    if (result.kind === "complete") {
      assert.equal(result.frame.payload.length, 0);
    }
  });

  // ── binary payload ──────────────────────────────────────────────

  it("handles binary (non-UTF8) payload", async () => {
    const rx = makeRx();
    await rx.bind();
    const rxAddr = rx.address()!;

    const tx = makeTx();
    await tx.bind();

    const payload = Buffer.from([0x00, 0xFF, 0xFE, 0x80, 0x01]);
    const frame = buildDgram(TYPE_NOTIFY, 0, payload);

    const received = new Promise<Buffer>((resolve) => {
      rx.onMessage = (data) => resolve(data);
    });

    await tx.send(frame, rxAddr.port, "127.0.0.1");

    const data = await received;
    const result = parseDgram(data);
    assert.equal(result.kind, "complete");
    if (result.kind === "complete") {
      assert.deepEqual(result.frame.payload, payload);
    }
  });
});
