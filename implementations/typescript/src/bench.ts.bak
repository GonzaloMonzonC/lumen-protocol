/**
 * LUMEN Benchmark Harness — collects detailed metrics for comparison charts.
 *
 * Usage: node --import tsx src/bench.ts > bench.json
 *
 * Categories tested:
 *   A. FrameAssembler throughput at various chunk sizes
 *   B. Compression ratio: JSON vs LUMEN binary
 *   C. encodeHyb128 / decodeHyb128 microbenchmarks
 *   D. Dict lookup speed: linear vs O(1) Map
 */

import { FrameAssembler } from "./frame-assembler.js";
import { buildFrame, buildSize, parseFrame, TYPE_REQUEST, TYPE_NOTIFY, FLAG_COMPRESSED } from "./frame.js";
import { encodeHyb128, decodeHyb128 } from "./hyb128.js";
import { compressValue, decompressValue } from "./compress.js";
import { lookupDictId } from "./dict.js";

// ── Types ──────────────────────────────────────────────────────────────────

interface BenchResult {
  name: string;
  category: string;
  ops: number;
  durationMs: number;
  opsPerSec: number;
  bytesProcessed: number;
  bytesPerSec: number;
  extra?: Record<string, number | string>;
}

interface BenchReport {
  timestamp: string;
  platform: string;
  nodeVersion: string;
  results: BenchResult[];
}

// ── Timer helper ───────────────────────────────────────────────────────────

function bench(name: string, category: string, fn: () => void, ops?: number): BenchResult {
  const warmup = 5;
  for (let i = 0; i < warmup; i++) fn();

  const runs = ops ?? 1000;
  const start = performance.now();
  for (let i = 0; i < runs; i++) fn();
  const durationMs = performance.now() - start;

  const opsPerSec = Math.round((runs / durationMs) * 1000);
  return { name, category, ops: runs, durationMs: Math.round(durationMs * 100) / 100, opsPerSec, bytesProcessed: 0, bytesPerSec: 0 };
}

// ── A. FrameAssembler throughput ──────────────────────────────────────────

function benchAssembler() {
  const payloads = {
    tiny: 16,
    small: 256,
    medium: 4096,
    large: 65536,
    xlarge: 262144, // 256 KB
  };

  const results: BenchResult[] = [];

  for (const [label, size] of Object.entries(payloads)) {
    const payload = new Uint8Array(size);
    payload.fill(0x41);

    // Build one frame
    const total = buildSize(size);
    const frame = new Uint8Array(total);
    buildFrame(TYPE_REQUEST, 0, payload, frame, 0);

    // Chunk sizes to test
    const chunkSizes = [1, 16, 64, 256, 1024, 4096, Number.MAX_SAFE_INTEGER];

    for (const cs of chunkSizes) {
      const csLabel = cs === Number.MAX_SAFE_INTEGER ? "full" : String(cs);
      const actualCs = cs === Number.MAX_SAFE_INTEGER ? frame.length : cs;

      // Pre-slice into chunks
      const chunks: Uint8Array[] = [];
      for (let i = 0; i < frame.length; i += actualCs) {
        chunks.push(frame.subarray(i, Math.min(i + actualCs, frame.length)));
      }

      const runs = size > 16384 ? 100 : 500;

      // Warmup
      for (let w = 0; w < 5; w++) {
        const a = new FrameAssembler();
        for (const c of chunks) a.push(c);
      }

      const start = performance.now();
      for (let r = 0; r < runs; r++) {
        const a = new FrameAssembler();
        for (const c of chunks) a.push(c);
      }
      const durationMs = performance.now() - start;

      const totalBytes = frame.length * runs;
      const bytesPerSec = Math.round(totalBytes / (durationMs / 1000));
      const opsPerSec = Math.round((runs / durationMs) * 1000);

      results.push({
        name: `FrameAssembler ${label}(${size}B) chunk=${csLabel}`,
        category: "assembler",
        ops: runs,
        durationMs: Math.round(durationMs * 100) / 100,
        opsPerSec,
        bytesProcessed: totalBytes,
        bytesPerSec,
        extra: { payloadSize: size, chunkSize: csLabel === "full" ? frame.length : actualCs, numChunks: chunks.length },
      });
    }
  }

  return results;
}

// ── B. Compression ratio ──────────────────────────────────────────────────

function benchCompression() {
  const testObjects: Array<{ name: string; obj: Record<string, unknown> }> = [
    {
      name: "initialize",
      obj: JSON.parse(JSON.stringify({
        jsonrpc: "2.0", id: 1, method: "initialize",
        params: { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "lumen-test", version: "1.0" } },
      })),
    },
    {
      name: "tools_list",
      obj: JSON.parse(JSON.stringify({ jsonrpc: "2.0", id: 2, result: { tools: [
        { name: "read", description: "Read file", inputSchema: { type: "object", properties: { path: { type: "string" } }, required: ["path"] } },
        { name: "write", description: "Write file", inputSchema: { type: "object", properties: { path: { type: "string" }, content: { type: "string" } }, required: ["path", "content"] } },
        { name: "delete", description: "Delete file", inputSchema: { type: "object", properties: { path: { type: "string" } }, required: ["path"] } },
        { name: "execute", description: "Execute command", inputSchema: { type: "object", properties: { command: { type: "string" }, arguments: { type: "array" } }, required: ["command"] } },
        { name: "search", description: "Search files", inputSchema: { type: "object", properties: { query: { type: "string" }, path: { type: "string" } }, required: ["query"] } },
      ] } })),
    },
    {
      name: "llm_request",
      obj: {
        model: "gpt-4", temperature: 0.7, max_tokens: 4096,
        messages: [
          { role: "system", content: "You are helpful." },
          { role: "user", content: "Explain LUMEN protocol." },
        ],
        tools: [{ type: "function", function: { name: "search", description: "Search web", parameters: { type: "object", properties: { query: { type: "string" } } } } }],
      },
    },
    {
      name: "error_response",
      obj: { jsonrpc: "2.0", id: 5, error: { code: -32601, message: "Method not found", data: { method: "unknown_tool", severity: "error", details: "The requested tool does not exist" } } },
    },
    {
      name: "big_result",
      obj: {
        jsonrpc: "2.0", id: 8, result: {
          content: [{ type: "text", text: "A".repeat(5000) }],
          usage: { prompt_tokens: 120, completion_tokens: 5000, total_tokens: 5120 },
          model: "deepseek-v4", finish_reason: "stop",
        },
      },
    },
  ];

  const results: BenchResult[] = [];

  for (const { name, obj } of testObjects) {
    const jsonStr = JSON.stringify(obj);
    const jsonBytes = new TextEncoder().encode(jsonStr).length;

    // Compress 1000 times
    const runs = 1000;
    const start = performance.now();
    for (let i = 0; i < runs; i++) {
      compressValue(obj);
    }
    const durationMs = performance.now() - start;

    // Average compressed size
    const compressed = compressValue(obj);
    const compBytes = compressed.length;
    const ratio = (compBytes / jsonBytes * 100).toFixed(1);

    results.push({
      name: `Compress ${name}`,
      category: "compression",
      ops: runs,
      durationMs: Math.round(durationMs * 100) / 100,
      opsPerSec: Math.round((runs / durationMs) * 1000),
      bytesProcessed: jsonBytes * runs,
      bytesPerSec: Math.round((jsonBytes * runs) / (durationMs / 1000)),
      extra: { objectName: name, jsonBytes, compressedBytes: compBytes, ratioPercent: parseFloat(ratio), savedBytes: jsonBytes - compBytes },
    });
  }

  return results;
}

// ── C. Hyb128 microbenchmarks ─────────────────────────────────────────────

function benchHyb128() {
  const values = [0, 1, 31, 63, 64, 255, 1000, 65535, 65536, 100000, 1000000];
  const results: BenchResult[] = [];

  // Encode
  for (const v of values) {
    const buf = new Uint8Array(11);
    const runs = 100_000;
    const start = performance.now();
    for (let i = 0; i < runs; i++) {
      encodeHyb128(v, buf, 0);
    }
    const durationMs = performance.now() - start;
    results.push({
      name: `encodeHyb128(${v})`,
      category: "hyb128_encode",
      ops: runs,
      durationMs: Math.round(durationMs * 100) / 100,
      opsPerSec: Math.round((runs / durationMs) * 1000),
      bytesProcessed: 0,
      bytesPerSec: 0,
      extra: { value: v, mode: v <= 63 ? "00" : v <= 65535 ? "10" : "11" },
    });
  }

  // Decode: build encoded bytes first
  for (const v of values) {
    const buf = new Uint8Array(11);
    const len = encodeHyb128(v, buf, 0);
    const encoded = buf.subarray(0, len);

    const runs = 100_000;
    const start = performance.now();
    for (let i = 0; i < runs; i++) {
      decodeHyb128(encoded, 0);
    }
    const durationMs = performance.now() - start;
    results.push({
      name: `decodeHyb128(${v})`,
      category: "hyb128_decode",
      ops: runs,
      durationMs: Math.round(durationMs * 100) / 100,
      opsPerSec: Math.round((runs / durationMs) * 1000),
      bytesProcessed: 0,
      bytesPerSec: 0,
      extra: { value: v, headerBytes: len },
    });
  }

  return results;
}

// ── D. Dict lookup speed ──────────────────────────────────────────────────

function benchDict() {
  const keys = ["tool", "arguments", "result", "error", "id", "name", "description", "content", "text", "type", "method", "params", "jsonrpc", "data", "code", "message"];
  const results: BenchResult[] = [];

  // O(1) Map lookup
  const runs = 1_000_000;
  const start = performance.now();
  for (let i = 0; i < runs; i++) {
    lookupDictId(keys[i % keys.length]);
  }
  const durationMs = performance.now() - start;
  results.push({
    name: "dict_lookup O(1)",
    category: "dict",
    ops: runs,
    durationMs: Math.round(durationMs * 100) / 100,
    opsPerSec: Math.round((runs / durationMs) * 1000),
    bytesProcessed: 0,
    bytesPerSec: 0,
    extra: { totalKeys: keys.length },
  });

  return results;
}

// ── Main ───────────────────────────────────────────────────────────────────

const report: BenchReport = {
  timestamp: new Date().toISOString(),
  platform: `${process.platform} ${process.arch}`,
  nodeVersion: process.version,
  results: [],
};

console.error("=== LUMEN Benchmark Suite ===");
console.error(`Platform: ${report.platform}`);
console.error(`Node: ${report.nodeVersion}`);
console.error("");

console.error("A. FrameAssembler throughput...");
report.results.push(...benchAssembler());

console.error("B. Compression ratio...");
report.results.push(...benchCompression());

console.error("C. Hyb128 microbenchmarks...");
report.results.push(...benchHyb128());

console.error("D. Dict lookup speed...");
report.results.push(...benchDict());

// Output JSON to stdout
console.log(JSON.stringify(report, null, 2));
console.error("");
console.error(`Done. ${report.results.length} benchmarks collected.`);
