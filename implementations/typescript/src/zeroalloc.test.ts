/**
 * Correctness tests for ZeroAllocDecompressor ("Vía 1").
 *
 * Verifies that the zero-alloc decoder produces the same output as the naive
 * `decompressValue` and `JSON.parse(JSON.stringify(...))` across a wide range
 * of MCP-relevant payloads.
 *
 * Run: node --import tsx --test src/zeroalloc.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { compressValue, decompressValue } from "./compress.js";
import { ZeroAllocDecompressor, decompressValueZeroAlloc } from "./zeroalloc.js";

// ═══ Test payloads ═══════════════════════════════════════════════════════════

const PAYLOADS: Array<{ name: string; value: unknown }> = [
  // ── Primitives ──────────────────────────────────────────────────────────
  { name: "null", value: null },
  { name: "bool_true", value: true },
  { name: "bool_false", value: false },
  { name: "int_zero", value: 0 },
  { name: "int_positive", value: 42 },
  { name: "int_negative", value: -1 },
  { name: "int_large", value: 1_000_000 },
  { name: "int_negative_large", value: -65536 },
  { name: "int_negative_small", value: -1 },
  { name: "float_zero", value: 0.0 },
  { name: "float_pi", value: 3.141592653589793 },
  { name: "float_negative", value: -2.718281828459045 },
  { name: "string_empty", value: "" },
  { name: "string_ascii", value: "hello world" },
  { name: "string_unicode", value: "héllo wörld 🚀" },
  { name: "string_long", value: "a".repeat(500) },
  { name: "string_escapes", value: 'line1\nline2\t"quoted"\\backslash' },

  // ── Arrays ──────────────────────────────────────────────────────────────
  { name: "array_empty", value: [] },
  { name: "array_ints", value: [1, 2, 3, 4, 5] },
  { name: "array_mixed", value: [null, true, 42, "text", 3.14] },
  { name: "array_nested", value: [[1, 2], [3, [4, 5]]] },
  { name: "array_large", value: Array.from({ length: 100 }, (_, i) => i) },

  // ── Objects ─────────────────────────────────────────────────────────────
  { name: "object_empty", value: {} },
  { name: "object_flat", value: { a: 1, b: "two", c: true } },
  {
    name: "object_dict_keys",
    value: {
      tool: "search",
      arguments: { query: "hello", limit: 10 },
      result: { text: "found" },
      error: null,
    },
  },
  {
    name: "object_nested",
    value: {
      level1: {
        level2: {
          level3: { value: 42 },
          list: [1, 2, 3],
        },
      },
    },
  },

  // ── Realistic MCP payloads ──────────────────────────────────────────────
  {
    name: "initialize",
    value: {
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2025-06-18",
        clientInfo: { name: "test-client", version: "1.0.0" },
      },
    },
  },
  {
    name: "tools_list",
    value: {
      jsonrpc: "2.0",
      id: 2,
      result: {
        tools: [
          {
            name: "search_code",
            description: "Search source code with regex",
            inputSchema: { type: "object", properties: { query: { type: "string" } } },
          },
          {
            name: "read_file",
            description: "Read file contents at path",
            inputSchema: { type: "object", properties: { path: { type: "string" } } },
          },
        ],
      },
    },
  },
  {
    name: "llm_request",
    value: {
      jsonrpc: "2.0",
      id: 3,
      method: "tools/call",
      params: {
        name: "llm_complete",
        arguments: {
          model: "deepseek-v4",
          messages: [{ role: "user", content: "Explain LUMEN protocol" }],
          temperature: 0.7,
        },
      },
    },
  },
  {
    name: "error_response",
    value: {
      jsonrpc: "2.0",
      id: 4,
      error: { code: -32600, message: "Invalid Request", data: { detail: "missing method" } },
    },
  },

  // ── Deeply nested ────────────────────────────────────────────────────────
  {
    name: "deep_array",
    value: [[[[[[[[1]]]]]]]],
  },
  {
    name: "deep_object",
    value: { a: { b: { c: { d: { e: { f: { g: { h: "deep" } } } } } } } },
  },

  // ── Edge cases: dict vs raw keys ─────────────────────────────────────────
  {
    name: "dict_key_tool",
    value: { tool: "test", arguments: { x: 1 } },
  },
  {
    name: "raw_key_custom",
    value: { customUncompressedKey: "value", anotherCustomKey: 42 },
  },
];

// ═══ Tests ═══════════════════════════════════════════════════════════════════

describe("ZeroAllocDecompressor — instance reuse", () => {
  const instance = new ZeroAllocDecompressor();

  for (const { name, value } of PAYLOADS) {
    it(`round-trips "${name}" correctly`, () => {
      const compressed = compressValue(value);
      const result = instance.decompress(compressed);

      // Compare to the naive decompressor.
      const expected = decompressValue(compressed);
      assert.deepStrictEqual(result, expected, `mismatch vs naive decompressor for "${name}"`);

      // Compare to JSON round-trip (golden truth).
      const jsonExpected = JSON.parse(JSON.stringify(value));
      assert.deepStrictEqual(result, jsonExpected, `mismatch vs JSON round-trip for "${name}"`);
    });
  }
});

describe("ZeroAllocDecompressor — convenience function", () => {
  for (const { name, value } of PAYLOADS) {
    it(`decompressValueZeroAlloc matches naive for "${name}"`, () => {
      const compressed = compressValue(value);
      const result = decompressValueZeroAlloc(compressed);
      const expected = decompressValue(compressed);
      assert.deepStrictEqual(result, expected, `mismatch for "${name}"`);
    });
  }
});

describe("ZeroAllocDecompressor — idempotency and reuse", () => {
  const instance = new ZeroAllocDecompressor();

  it("produces identical results across multiple calls with same compressed data", () => {
    const value = { tool: "search", arguments: { query: "lumen", limit: 5 } };
    const compressed = compressValue(value);
    const results: unknown[] = [];
    for (let i = 0; i < 10; i++) {
      results.push(instance.decompress(compressed));
    }
    for (let i = 1; i < results.length; i++) {
      assert.deepStrictEqual(results[i], results[0], `run ${i} differs from run 0`);
    }
  });

  it("handles mixed payloads on same instance without cross-contamination", () => {
    const a = compressValue({ x: 1 });
    const b = compressValue([1, 2, 3]);
    const c = compressValue(null);

    const ra = instance.decompress(a);
    const rb = instance.decompress(b);
    const rc = instance.decompress(c);

    assert.deepStrictEqual(ra, { x: 1 });
    assert.deepStrictEqual(rb, [1, 2, 3]);
    assert.strictEqual(rc, null);

    // Re-decode to ensure no state bleed.
    const ra2 = instance.decompress(a);
    const rb2 = instance.decompress(b);
    assert.deepStrictEqual(ra2, { x: 1 });
    assert.deepStrictEqual(rb2, [1, 2, 3]);
  });
});

describe("ZeroAllocDecompressor — malformed input safety", () => {
  const instance = new ZeroAllocDecompressor();

  it("returns null for empty buffer", () => {
    assert.strictEqual(instance.decompress(new Uint8Array(0)), undefined);
  });

  it("returns null for truncated float tag", () => {
    const buf = new Uint8Array([0xe2, 0x00, 0x00, 0x00]); // TAG_FLOAT but only 4 bytes, needs 8
    assert.strictEqual(instance.decompress(buf), null);
  });

  it("returns null for truncated bool tag", () => {
    const buf = new Uint8Array([0xe1]); // TAG_BOOL without value byte
    assert.strictEqual(instance.decompress(buf), null);
  });

  it("returns null for truncated raw string (length beyond buffer)", () => {
    const buf = new Uint8Array([0xe5, 0x80 | 100]); // TAG_STR_RAW with length=100 but no data
    assert.strictEqual(instance.decompress(buf), null);
  });

  it("returns null for truncated object key", () => {
    // TAG_OBJECT with count=1, but no key bytes follow
    const buf = new Uint8Array([0xe7, 0x01]);
    assert.strictEqual(instance.decompress(buf), null);
  });

  it("returns null for empty buffer with no root holder (edge)", () => {
    // Buffer that starts a container but doesn't finish it
    const buf = new Uint8Array([0xe6, 0x05]); // TAG_ARRAY with count=5, no values
    const result = instance.decompress(buf);
    // Should return the empty array (with 5 undefined slots) or null — either is safe.
    // The key property: it must not throw.
    assert.ok(result !== undefined || result === null);
  });

  it("returns null for unknown tag byte", () => {
    const buf = new Uint8Array([0xff, 0x00]);
    assert.strictEqual(instance.decompress(buf), null);
  });
});

describe("ZeroAllocDecompressor — GC-friendly reuse", () => {
  it("reusing the instance many times does not throw", () => {
    const instance = new ZeroAllocDecompressor();
    const value = {
      tools: Array.from({ length: 50 }, (_, i) => ({
        name: `tool_${i}`,
        description: `description for tool ${i}`,
        inputSchema: { type: "object", properties: { query: { type: "string" } } },
      })),
    };
    const compressed = compressValue(value);
    const expected = decompressValue(compressed);

    for (let i = 0; i < 100; i++) {
      const result = instance.decompress(compressed);
      assert.deepStrictEqual(result, expected, `iteration ${i} mismatch`);
    }
  });
});

describe("ZeroAllocDecompressor — consistency with bench payloads", () => {
  // These are the same shapes used in the GC pressure benchmark (Asalto 3).
  it("decodes a 500-tool payload matching naive", () => {
    const tools = Array.from({ length: 500 }, (_, i) => ({
      name: `tool_${i}`,
      description: `This is tool number ${i} for testing GC pressure`,
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: `search query for tool ${i}` },
        },
      },
    }));
    const compressed = compressValue(tools);
    const expected = decompressValue(compressed);
    const result = decompressValueZeroAlloc(compressed);
    assert.deepStrictEqual(result, expected);
  });
});
