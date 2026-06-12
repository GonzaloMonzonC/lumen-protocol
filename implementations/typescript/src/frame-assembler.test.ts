/**
 * Stress tests for FrameAssembler — zero-allocation streaming parser.
 *
 * Run: node --import tsx --test src/frame-assembler.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { FrameAssembler } from "./frame-assembler.js";
import {
  buildFrame,
  buildSize,
  TYPE_REQUEST,
  TYPE_RESPONSE,
  TYPE_NOTIFY,
  TYPE_PROBE,
  TYPE_PROBE_ACK,
  FLAG_COMPRESSED,
  FLAG_ENCRYPTED,
  FLAG_PRIORITY,
} from "./frame.js";

// ── Helpers ────────────────────────────────────────────────────────────────

function makeFrame(ft: number, flags: number, payload: Uint8Array): Uint8Array {
  const total = buildSize(payload.length);
  const buf = new Uint8Array(total);
  buildFrame(ft, flags, payload, buf, 0);
  return buf;
}

function chunkify(data: Uint8Array, size: number): Uint8Array[] {
  const out: Uint8Array[] = [];
  for (let i = 0; i < data.length; i += size) {
    out.push(data.subarray(i, Math.min(i + size, data.length)));
  }
  return out;
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe("FrameAssembler", () => {

  it("emits a complete frame from a single chunk", () => {
    const payload = new TextEncoder().encode(JSON.stringify({ jsonrpc: "2.0", method: "ping" }));
    const frame = makeFrame(TYPE_REQUEST, 0, payload);
    const a = new FrameAssembler();
    const frames = a.push(frame);
    assert.equal(frames.length, 1);
    assert.equal(frames[0].frameType, TYPE_REQUEST);
    assert.equal(frames[0].flags, 0);
    assert.deepEqual(new TextDecoder().decode(frames[0].payload), '{"jsonrpc":"2.0","method":"ping"}');
  });

  it("emits multiple frames from a single chunk", () => {
    const p1 = new TextEncoder().encode(JSON.stringify({ a: 1 }));
    const p2 = new TextEncoder().encode(JSON.stringify({ b: 2 }));
    const p3 = new TextEncoder().encode(JSON.stringify({ c: 3 }));
    const f1 = makeFrame(TYPE_NOTIFY, 0, p1);
    const f2 = makeFrame(TYPE_RESPONSE, FLAG_COMPRESSED, p2);
    const f3 = makeFrame(TYPE_REQUEST, FLAG_PRIORITY, p3);
    const mega = new Uint8Array(f1.length + f2.length + f3.length);
    mega.set(f1, 0);
    mega.set(f2, f1.length);
    mega.set(f3, f1.length + f2.length);
    const a = new FrameAssembler();
    const frames = a.push(mega);
    assert.equal(frames.length, 3);
    assert.equal(frames[0].frameType, TYPE_NOTIFY);
    assert.equal(frames[1].frameType, TYPE_RESPONSE);
    assert.equal(frames[2].frameType, TYPE_REQUEST);
    assert.equal(frames[1].flags, FLAG_COMPRESSED);
    assert.equal(frames[2].flags, FLAG_PRIORITY);
  });

  it("reassembles a frame delivered 1 byte at a time", () => {
    const payload = new TextEncoder().encode("hello lumen");
    const frame = makeFrame(TYPE_NOTIFY, 0, payload);
    const chunks = chunkify(frame, 1);
    const a = new FrameAssembler();
    const all: ReturnType<typeof a.push> = [];
    for (const c of chunks) all.push(...a.push(c));
    assert.equal(all.length, 1);
    assert.equal(all[0].frameType, TYPE_NOTIFY);
    assert.equal(new TextDecoder().decode(all[0].payload), "hello lumen");
  });

  it("reassembles a frame split across 3 uneven chunks", () => {
    const payload = new TextEncoder().encode("x".repeat(200));
    const frame = makeFrame(TYPE_RESPONSE, 0, payload);
    const a = new FrameAssembler();
    let frames = a.push(frame.subarray(0, 3));
    assert.equal(frames.length, 0);
    frames = a.push(frame.subarray(3, 7));
    assert.equal(frames.length, 0);
    frames = a.push(frame.subarray(7));
    assert.equal(frames.length, 1);
    assert.equal(new TextDecoder().decode(frames[0].payload), "x".repeat(200));
  });

  it("handles Hyb128 header split across chunks", () => {
    const payload = new Uint8Array(200);
    const frame = makeFrame(TYPE_PROBE, 0, payload);
    const a = new FrameAssembler();
    let frames = a.push(frame.subarray(0, 1));
    assert.equal(frames.length, 0);
    frames = a.push(frame.subarray(1));
    assert.equal(frames.length, 1);
    assert.equal(frames[0].frameType, TYPE_PROBE);
    assert.equal(frames[0].payload.length, 200);
  });

  it("handles empty chunks gracefully", () => {
    const a = new FrameAssembler();
    assert.equal(a.push(new Uint8Array(0)).length, 0);
    const payload = new TextEncoder().encode("ok");
    const frame = makeFrame(TYPE_NOTIFY, 0, payload);
    const frames = a.push(frame);
    assert.equal(frames.length, 1);
    assert.equal(new TextDecoder().decode(frames[0].payload), "ok");
  });

  it("handles short frames (6-bit Hyb128)", () => {
    const payload = new TextEncoder().encode("short");
    const frame = makeFrame(TYPE_NOTIFY, 0, payload);
    assert.equal(frame[0] >> 6, 0); // mode 00
    const a = new FrameAssembler();
    const frames = a.push(frame);
    assert.equal(frames.length, 1);
    assert.equal(new TextDecoder().decode(frames[0].payload), "short");
  });

  it("handles exactly 63-byte payload (mode 00 boundary)", () => {
    const payload = new Uint8Array(63);
    payload.fill(0x41);
    const frame = makeFrame(TYPE_NOTIFY, 0, payload);
    assert.equal(frame[0] >> 6, 0); // mode 00
    const a = new FrameAssembler();
    const frames = a.push(frame);
    assert.equal(frames.length, 1);
    assert.equal(frames[0].payload.length, 63);
  });

  it("handles 64-byte payload (mode 10, u16 LE)", () => {
    const payload = new Uint8Array(64);
    payload.fill(0x42);
    const frame = makeFrame(TYPE_NOTIFY, 0, payload);
    assert.equal(frame[0] >> 6, 2); // mode 10
    const a = new FrameAssembler();
    const frames = a.push(frame);
    assert.equal(frames.length, 1);
    assert.equal(frames[0].payload.length, 64);
  });

  it("handles large frames (mode 11, u32 LE) in 1024-byte chunks", () => {
    const payload = new Uint8Array(70_000);
    payload.fill(0x58);
    const frame = makeFrame(TYPE_REQUEST, FLAG_COMPRESSED, payload);
    const chunks = chunkify(frame, 1024);
    const a = new FrameAssembler();
    const all: ReturnType<typeof a.push> = [];
    for (const c of chunks) all.push(...a.push(c));
    assert.equal(all.length, 1);
    assert.equal(all[0].payload.length, 70_000);
    assert.equal(all[0].frameType, TYPE_REQUEST);
  });

  it("handles PROBE and PROBE_ACK back-to-back", () => {
    const probeFrame = makeFrame(TYPE_PROBE, 0, new Uint8Array(0));
    const ackPayload = new TextEncoder().encode(JSON.stringify({ v: 1 }));
    const ackFrame = makeFrame(TYPE_PROBE_ACK, 0, ackPayload);
    const combined = new Uint8Array(probeFrame.length + ackFrame.length);
    combined.set(probeFrame, 0);
    combined.set(ackFrame, probeFrame.length);
    const a = new FrameAssembler();
    const frames = a.push(combined);
    assert.equal(frames.length, 2);
    assert.equal(frames[0].frameType, TYPE_PROBE);
    assert.equal(frames[0].payload.length, 0);
    assert.equal(frames[1].frameType, TYPE_PROBE_ACK);
    assert.equal(new TextDecoder().decode(frames[1].payload), '{"v":1}');
  });

  it("reset() clears internal state", () => {
    const payload = new TextEncoder().encode("partial");
    const frame = makeFrame(TYPE_NOTIFY, 0, payload);
    const a = new FrameAssembler();
    a.push(frame.subarray(0, 2));
    a.reset();
    const frames = a.push(frame);
    assert.equal(frames.length, 1);
    assert.equal(new TextDecoder().decode(frames[0].payload), "partial");
  });

  it("flush() returns trailing bytes on incomplete frame", () => {
    const payload = new TextEncoder().encode("incomplete data here");
    const frame = makeFrame(TYPE_NOTIFY, 0, payload);
    const a = new FrameAssembler();
    const frames = a.push(frame.subarray(0, 5));
    assert.equal(frames.length, 0);
    const leftover = a.flush();
    assert.notEqual(leftover, null);
    assert.equal(leftover!.length, 5);
    assert.deepEqual(leftover!, frame.subarray(0, 5));
    const frames2 = a.push(frame);
    assert.equal(frames2.length, 1);
    assert.equal(new TextDecoder().decode(frames2[0].payload), "incomplete data here");
  });

  it("reassembles 10 MCP messages in awkward 37-byte chunks", () => {
    const messages = [
      JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2024-11-05" } }),
      JSON.stringify({ jsonrpc: "2.0", id: 2, result: { serverInfo: { name: "test" } } }),
      JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }),
      JSON.stringify({ jsonrpc: "2.0", id: 3, method: "tools/list" }),
      JSON.stringify({ jsonrpc: "2.0", id: 3, result: { tools: [{ name: "read" }, { name: "write" }] } }),
      JSON.stringify({ jsonrpc: "2.0", id: 4, method: "resources/read", params: { uri: "file:///test" } }),
      JSON.stringify({ jsonrpc: "2.0", id: 5, method: "prompts/get", params: { name: "review" } }),
      JSON.stringify({ jsonrpc: "2.0", id: 6, method: "completion/complete" }),
      JSON.stringify({ jsonrpc: "2.0", id: 7, error: { code: -32601, message: "Method not found" } }),
      JSON.stringify({ jsonrpc: "2.0", id: 8, result: { content: "done" } }),
    ];
    const frames = messages.map((m) => makeFrame(TYPE_REQUEST, FLAG_COMPRESSED, new TextEncoder().encode(m)));
    const totalLen = frames.reduce((acc, f) => acc + f.length, 0);
    const stream = new Uint8Array(totalLen);
    let pos = 0;
    for (const f of frames) { stream.set(f, pos); pos += f.length; }
    const chunks = chunkify(stream, 37);
    const a = new FrameAssembler();
    const received: string[] = [];
    for (const c of chunks) {
      for (const frame of a.push(c)) received.push(new TextDecoder().decode(frame.payload));
    }
    assert.equal(received.length, 10);
    for (let i = 0; i < messages.length; i++) {
      assert.equal(received[i], messages[i], `message ${i} mismatch`);
    }
  });

  it("correctly preserves FLAG_ENCRYPTED", () => {
    const payload = new TextEncoder().encode("secret");
    const frame = makeFrame(TYPE_REQUEST, FLAG_ENCRYPTED | FLAG_PRIORITY, payload);
    const a = new FrameAssembler();
    const frames = a.push(frame);
    assert.equal(frames.length, 1);
    assert.equal(frames[0].flags & FLAG_ENCRYPTED, FLAG_ENCRYPTED);
    assert.equal(frames[0].flags & FLAG_PRIORITY, FLAG_PRIORITY);
  });

  it("emits complete frame and buffers the next incomplete one", () => {
    const p1 = new TextEncoder().encode("first");
    const p2 = new TextEncoder().encode("second");
    const f1 = makeFrame(TYPE_NOTIFY, 0, p1);
    const f2 = makeFrame(TYPE_RESPONSE, 0, p2);
    const combined = new Uint8Array(f1.length + 2);
    combined.set(f1, 0);
    combined.set(f2.subarray(0, 2), f1.length);
    const a = new FrameAssembler();
    const frames = a.push(combined);
    assert.equal(frames.length, 1);
    assert.equal(new TextDecoder().decode(frames[0].payload), "first");
    const frames2 = a.push(f2.subarray(2));
    assert.equal(frames2.length, 1);
    assert.equal(new TextDecoder().decode(frames2[0].payload), "second");
  });

  it("handles zero-length payload frames", () => {
    const frame = makeFrame(TYPE_NOTIFY, 0, new Uint8Array(0));
    const a = new FrameAssembler();
    const frames = a.push(frame);
    assert.equal(frames.length, 1);
    assert.equal(frames[0].payload.length, 0);
  });
});
