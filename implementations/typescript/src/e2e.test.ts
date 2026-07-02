/**
 * LUMEN e2e cross-implementation test — TypeScript.
 *
 * Validates that the TypeScript implementation produces binary output
 * identical to the Python golden binaries, and that cross-decoding works.
 *
 * Run: node --import tsx --test src/e2e.test.ts
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";

import { compressValue, decompressValue } from "./compress.js";
import {
  buildFrame,
  buildSize,
  parseFrame,
  FrameAssembler,
  TYPE_REQUEST,
  TYPE_RESPONSE,
  TYPE_NOTIFY,
  FLAG_COMPRESSED,
  FLAG_PRIORITY,
} from "./index.js";
import { encodeHyb128, decodeHyb128, encodedLen } from "./hyb128.js";

// This package compiles to CommonJS, so __dirname is available at runtime.
// src/ and dist/ sit at the same depth, so the relative path works for both.
const VECTORS_PATH = join(__dirname, "..", "..", "..", "tests", "e2e", "shared_vectors.json");
const GOLDEN_DIR = join(__dirname, "..", "..", "..", "tests", "e2e", "golden");

function hashBytes(data: Uint8Array): string {
  return createHash("sha256").update(data).digest("hex").substring(0, 16);
}

function loadVectors(): Array<{ name: string; value: unknown }> {
  const raw = readFileSync(VECTORS_PATH, "utf-8");
  const data = JSON.parse(raw);
  return data.vectors;
}

function loadGolden(name: string): Uint8Array | null {
  const path = join(GOLDEN_DIR, `${name}.lumen`);
  if (!existsSync(path)) return null;
  return new Uint8Array(readFileSync(path));
}

function loadGoldenFrame(name: string): Uint8Array | null {
  const path = join(GOLDEN_DIR, `${name}.frame`);
  if (!existsSync(path)) return null;
  return new Uint8Array(readFileSync(path));
}

function buffersEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

/** Whether a payload name represents JSON content. */
function isJsonPayload(name: string): boolean {
  return name.startsWith("json_");
}

// Vectors with known cross-implementation binary differences:
// - float_zero: TS encodes 0.0 as TAG_INT (2B), Python as TAG_FLOAT (9B). Both valid.
const SKIP_BINARY_COMPARE = new Set(["float_zero"]);

// Vectors skipped entirely in TS (known bugs) — none after LEB128 zigzag fix
const SKIP_TS: Set<string> = new Set();

// ═══════════════════════════════════════════════════════════════════════════════
// 1. Compress roundtrip
// ═══════════════════════════════════════════════════════════════════════════════
describe("E2E — Compress Roundtrip", () => {
  const vectors = loadVectors();

  for (const v of vectors) {
    if (SKIP_TS.has(v.name)) {
      it(`roundtrip: ${v.name} [SKIP: known TS bug]`, () => {});
      continue;
    }
    it(`roundtrip: ${v.name}`, () => {
      const compressed = compressValue(v.value);
      const decompressed = decompressValue(compressed);
      assert.deepStrictEqual(decompressed, v.value);
    });
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// 2. Binary compatibility with Python golden files
// ═══════════════════════════════════════════════════════════════════════════════
describe("E2E — Binary Compatibility", () => {
  const vectors = loadVectors();

  for (const v of vectors) {
    if (SKIP_TS.has(v.name)) {
      it(`TS compress == Python golden: ${v.name} [SKIP]`, () => {});
      it(`TS decodes Python golden: ${v.name} [SKIP]`, () => {});
      continue;
    }

    it(`TS compress == Python golden: ${v.name}`, () => {
      const tsCompressed = compressValue(v.value);
      const golden = loadGolden(v.name);
      if (!golden) return;

      if (SKIP_BINARY_COMPARE.has(v.name)) return; // known semantic diff

      if (!buffersEqual(tsCompressed, golden)) {
        const tsHex = Buffer.from(tsCompressed).toString("hex");
        const pyHex = Buffer.from(golden).toString("hex");
        assert.fail(
          `Binary mismatch for "${v.name}":\n` +
          `  TS  (${tsCompressed.length}B): ${tsHex}\n` +
          `  PY  (${golden.length}B): ${pyHex}`
        );
      }
    });

    it(`TS decodes Python golden: ${v.name}`, () => {
      const golden = loadGolden(v.name);
      if (!golden) return;

      const decoded = decompressValue(golden);
      assert.deepStrictEqual(decoded, v.value,
        `TS failed to decode Python binary for "${v.name}"`);
    });
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// 3. Binary stability — same input → same binary every time
// ═══════════════════════════════════════════════════════════════════════════════
describe("E2E — Binary Stability", () => {
  const cases: Array<[string, unknown]> = [
    ["null", null], ["bool", true], ["int", 42], ["float", 3.14],
    ["string", "hello"], ["array", [1, 2, 3]], ["object", { key: "value" }],
    ["mcp_init", { jsonrpc: "2.0", method: "initialize" }],
  ];

  for (const [name, value] of cases) {
    it(`stability: ${name}`, () => {
      const c1 = compressValue(value);
      const c2 = compressValue(value);
      assert.ok(buffersEqual(c1, c2), "Non-deterministic compression!");
    });
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// 4. Hyb128 roundtrip
// ═══════════════════════════════════════════════════════════════════════════════
describe("E2E — Hyb128 Roundtrip", () => {
  const testValues: Array<[number, number]> = [
    [0, 1], [1, 1], [42, 1], [63, 1],
    [64, 3], [255, 3], [1000, 3], [65535, 3],
    [65536, 5], [100000, 5], [1000000, 5],
  ];

  for (const [value, expectedLen] of testValues) {
    it(`hyb128 ${value} → ${expectedLen}B`, () => {
      const buf = new Uint8Array(11);
      const n = encodeHyb128(value, buf);
      assert.equal(n, expectedLen);
      assert.equal(encodedLen(value), expectedLen);

      const decoded = decodeHyb128(buf);
      assert.ok(decoded !== null);
      assert.equal(decoded!.value, value);
      assert.equal(decoded!.headerLen, expectedLen);
    });
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// 5. Frame roundtrip
// ═══════════════════════════════════════════════════════════════════════════════
describe("E2E — Frame Roundtrip", () => {
  const payloads: Array<[string, Uint8Array]> = [
    ["empty", new Uint8Array(0)],
    ["hello", new TextEncoder().encode("hello")],
    ["json_small", new TextEncoder().encode(JSON.stringify({ method: "ping" }))],
    ["json_mcp", new TextEncoder().encode(JSON.stringify({
      jsonrpc: "2.0", id: 1, method: "initialize",
      params: { protocolVersion: "2025-06-18" },
    }))],
  ];
  const frameTypes: Array<[string, number]> = [
    ["REQUEST", TYPE_REQUEST], ["RESPONSE", TYPE_RESPONSE], ["NOTIFY", TYPE_NOTIFY],
  ];
  const flagSets: Array<[string, number]> = [
    ["none", 0], ["compressed", FLAG_COMPRESSED], ["priority", FLAG_PRIORITY],
  ];

  for (const [pname, payload] of payloads) {
    for (const [tname, ftype] of frameTypes) {
      for (const [flname, flags] of flagSets) {
        const name = `frame_${tname}_${flname}_${pname}`;
        it(name, () => {
          const buf = new Uint8Array(buildSize(payload.length));
          const n = buildFrame(ftype, flags, payload, buf);
          assert.equal(n, buf.length);

          const result = parseFrame(buf, 0);
          assert.equal(result.kind, "complete");
          if (result.kind === "complete") {
            assert.equal(result.frame.frameType, ftype);
            assert.equal(result.frame.flags, flags);
            assert.ok(buffersEqual(result.frame.payload, payload));
          }
        });
      }
    }
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// 6. Frame compatibility with Python golden frames
//    JSON payloads compared semantically (Python json.dumps adds ": " spacing;
//    JS JSON.stringify uses ":").  Non-JSON payloads compared byte-for-byte.
// ═══════════════════════════════════════════════════════════════════════════════
describe("E2E — Frame Binary Compatibility", () => {
  const payloads: Array<[string, Uint8Array]> = [
    ["empty", new Uint8Array(0)],
    ["hello", new TextEncoder().encode("hello")],
    ["json_small", new TextEncoder().encode(JSON.stringify({ method: "ping" }))],
    ["json_mcp", new TextEncoder().encode(JSON.stringify({
      jsonrpc: "2.0", id: 1, method: "initialize",
      params: { protocolVersion: "2025-06-18" },
    }))],
  ];
  const frameTypes: Array<[string, number]> = [
    ["REQUEST", TYPE_REQUEST], ["RESPONSE", TYPE_RESPONSE], ["NOTIFY", TYPE_NOTIFY],
  ];
  const flagSets: Array<[string, number]> = [
    ["none", 0], ["compressed", FLAG_COMPRESSED], ["priority", FLAG_PRIORITY],
  ];

  for (const [pname, payload] of payloads) {
    for (const [tname, ftype] of frameTypes) {
      for (const [flname, flags] of flagSets) {
        const name = `frame_${tname}_${flname}_${pname}`;

        it(`TS frame == Python golden: ${name}`, () => {
          const buf = new Uint8Array(buildSize(payload.length));
          buildFrame(ftype, flags, payload, buf);

          const golden = loadGoldenFrame(name);
          if (!golden) return;

          if (isJsonPayload(pname)) {
            // Semantic: frame header must match, payload compared as JSON
            assert.equal(buf.length > 2, true); // has header
            assert.equal(golden.length > 2, true);
            const tsResult = parseFrame(buf, 0);
            const pyResult = parseFrame(golden, 0);
            if (tsResult.kind === "complete" && pyResult.kind === "complete") {
              assert.equal(tsResult.frame.frameType, pyResult.frame.frameType);
              assert.equal(tsResult.frame.flags, pyResult.frame.flags);
              if (tsResult.frame.flags & FLAG_COMPRESSED) {
                // Compressed payload: decompress both and compare semantically
                const tsDec = decompressValue(tsResult.frame.payload);
                const pyDec = decompressValue(pyResult.frame.payload);
                assert.deepStrictEqual(tsDec, pyDec);
              } else {
                // Raw JSON payload: parse and compare
                const tsJson = JSON.parse(new TextDecoder().decode(tsResult.frame.payload));
                const pyJson = JSON.parse(new TextDecoder().decode(pyResult.frame.payload));
                assert.deepStrictEqual(tsJson, pyJson);
              }
            } else {
              assert.fail(`Failed to parse frames: TS=${tsResult.kind}, PY=${pyResult.kind}`);
            }
          } else {
            // Binary: non-JSON payloads must match byte-for-byte
            if (!buffersEqual(buf, golden)) {
              const tsHex = Buffer.from(buf).toString("hex");
              const pyHex = Buffer.from(golden).toString("hex");
              assert.fail(
                `Frame mismatch "${name}":\n` +
                `  TS (${buf.length}B): ${tsHex}\n` +
                `  PY (${golden.length}B): ${pyHex}`
              );
            }
          }
        });

        it(`TS parses Python frame: ${name}`, () => {
          const golden = loadGoldenFrame(name);
          if (!golden) return;

          const result = parseFrame(golden, 0);
          assert.equal(result.kind, "complete",
            `TS failed to parse Python frame "${name}": got ${result.kind}`);
          if (result.kind === "complete") {
            assert.equal(result.frame.frameType, ftype);
            assert.equal(result.frame.flags, flags);

            if (isJsonPayload(pname)) {
              // Semantic: compare parsed JSON objects
              const parsed = JSON.parse(new TextDecoder().decode(result.frame.payload));
              const expected = JSON.parse(new TextDecoder().decode(payload));
              assert.deepStrictEqual(parsed, expected,
                `JSON payload semantic mismatch for "${name}"`);
            } else {
              // Binary: non-JSON payloads must match
              assert.ok(buffersEqual(result.frame.payload, payload),
                `Payload mismatch for "${name}"`);
            }
          }
        });
      }
    }
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// 7. FrameAssembler
// ═══════════════════════════════════════════════════════════════════════════════
describe("E2E — FrameAssembler", () => {
  it("single frame", () => {
    const a = new FrameAssembler();
    const payload = new TextEncoder().encode("hello");
    const buf = new Uint8Array(buildSize(payload.length));
    buildFrame(TYPE_RESPONSE, 0, payload, buf);
    const frames = a.push(buf);
    assert.equal(frames.length, 1);
    assert.ok(buffersEqual(frames[0].payload, payload));
  });

  it("multiple frames in one chunk", () => {
    const a = new FrameAssembler();
    const p1 = new TextEncoder().encode("A");
    const p2 = new TextEncoder().encode("BB");
    const b1 = new Uint8Array(buildSize(p1.length));
    const b2 = new Uint8Array(buildSize(p2.length));
    buildFrame(TYPE_NOTIFY, 0, p1, b1);
    buildFrame(TYPE_RESPONSE, 0, p2, b2);
    const combined = new Uint8Array(b1.length + b2.length);
    combined.set(b1, 0);
    combined.set(b2, b1.length);
    const frames = a.push(combined);
    assert.equal(frames.length, 2);
    assert.ok(buffersEqual(frames[0].payload, p1));
    assert.ok(buffersEqual(frames[1].payload, p2));
  });

  it("chunked frame", () => {
    const a = new FrameAssembler();
    const payload = new TextEncoder().encode("chunked_test");
    const buf = new Uint8Array(buildSize(payload.length));
    buildFrame(TYPE_REQUEST, FLAG_COMPRESSED, payload, buf);
    const mid = Math.floor(buf.length / 2);
    const r1 = a.push(buf.subarray(0, mid));
    const r2 = a.push(buf.subarray(mid));
    assert.equal(r1.length + r2.length, 1);
    const all = [...r1, ...r2];
    assert.ok(buffersEqual(all[0].payload, payload));
  });

  it("reset", () => {
    const a = new FrameAssembler();
    const payload = new TextEncoder().encode("hello");
    const buf = new Uint8Array(buildSize(payload.length));
    buildFrame(TYPE_RESPONSE, 0, payload, buf);
    a.push(buf.subarray(0, 2));
    a.reset();
    const frames = a.push(buf);
    assert.equal(frames.length, 1);
    assert.ok(buffersEqual(frames[0].payload, payload));
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// 8. Compressed frame integration
// ═══════════════════════════════════════════════════════════════════════════════
describe("E2E — Compressed Frame Integration", () => {
  const payloads: Array<[string, unknown]> = [
    ["initialize", { jsonrpc: "2.0", id: 1, method: "initialize",
      params: { protocolVersion: "2025-06-18" } }],
    ["tools_list", { jsonrpc: "2.0", id: 2, result: {
      tools: [{ name: "search", description: "Search code",
        inputSchema: { type: "object", properties: { query: { type: "string" } } } }],
    } }],
  ];

  for (const [pname, payload] of payloads) {
    const name = `integration_${pname}`;
    it(`full cycle: ${name}`, () => {
      const compressed = compressValue(payload);
      const buf = new Uint8Array(buildSize(compressed.length));
      buildFrame(TYPE_REQUEST, FLAG_COMPRESSED, compressed, buf);

      // Verify against Python golden
      const golden = loadGoldenFrame(name);
      if (golden) {
        assert.ok(buffersEqual(buf, golden),
          `Integration frame mismatch for "${name}"`);
      }

      // Parse and decompress
      const result = parseFrame(buf, 0);
      assert.equal(result.kind, "complete");
      if (result.kind === "complete") {
        assert.equal(result.frame.flags, FLAG_COMPRESSED);
        const decompressed = decompressValue(result.frame.payload);
        assert.deepStrictEqual(decompressed, payload);
      }

      // Parse Python golden too
      if (golden) {
        const pyResult = parseFrame(golden, 0);
        assert.equal(pyResult.kind, "complete",
          `TS failed to parse Python integration frame "${name}"`);
        if (pyResult.kind === "complete") {
          const pyDecompressed = decompressValue(pyResult.frame.payload);
          assert.deepStrictEqual(pyDecompressed, payload,
            `TS failed to decompress Python integration frame payload "${name}"`);
        }
      }
    });
  }
});
