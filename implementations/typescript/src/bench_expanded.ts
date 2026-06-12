/**
 * LUMEN Benchmark Harness â€” expanded with JSON-RPC comparable benchmarks.
 */
import { FrameAssembler } from "./frame-assembler.js";
import { buildFrame, buildSize, TYPE_REQUEST } from "./frame.js";
import { encodeHyb128, decodeHyb128 } from "./hyb128.js";
import { compressValue, decompressValue } from "./compress.js";
import { lookupDictId } from "./dict.js";

interface BenchResult {
  name: string; category: string; ops: number; durationMs: number;
  opsPerSec: number; bytesProcessed: number; bytesPerSec: number;
  extra?: Record<string, number | string>;
}

interface BenchReport {
  timestamp: string; platform: string; nodeVersion: string;
  results: BenchResult[];
}

const MCP: Array<{ name: string; obj: Record<string, unknown> }> = [
  { name: "initialize", obj: JSON.parse(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "lumen-test", version: "1.0" } } })) },
  { name: "tools_list", obj: JSON.parse(JSON.stringify({ jsonrpc: "2.0", id: 2, result: { tools: [{ name: "read", description: "Read file", inputSchema: { type: "object", properties: { path: { type: "string" } }, required: ["path"] } }, { name: "write", description: "Write file", inputSchema: { type: "object", properties: { path: { type: "string" }, content: { type: "string" } }, required: ["path", "content"] } }, { name: "delete", description: "Delete file", inputSchema: { type: "object", properties: { path: { type: "string" } }, required: ["path"] } }, { name: "execute", description: "Execute command", inputSchema: { type: "object", properties: { command: { type: "string" }, arguments: { type: "array" } }, required: ["command"] } }, { name: "search", description: "Search files", inputSchema: { type: "object", properties: { query: { type: "string" }, path: { type: "string" } }, required: ["query"] } }] } })) },
  { name: "llm_request", obj: { model: "gpt-4", temperature: 0.7, max_tokens: 4096, messages: [{ role: "system", content: "You are helpful." }, { role: "user", content: "Explain LUMEN protocol." }], tools: [{ type: "function", function: { name: "search", description: "Search web", parameters: { type: "object", properties: { query: { type: "string" } } } } }] } },
  { name: "error_response", obj: { jsonrpc: "2.0", id: 5, error: { code: -32601, message: "Method not found", data: { method: "unknown_tool", severity: "error", details: "The requested tool does not exist" } } } },
  { name: "big_result", obj: { jsonrpc: "2.0", id: 8, result: { content: [{ type: "text", text: "A".repeat(5000) }], usage: { prompt_tokens: 120, completion_tokens: 5000, total_tokens: 5120 }, model: "deepseek-v4", finish_reason: "stop" } } },
];

// A. FrameAssembler
function benchAssembler(): BenchResult[] {
  const payloads: Record<string, number> = { tiny: 16, small: 256, medium: 4096, large: 65536, xlarge: 262144 };
  const r: BenchResult[] = [];
  for (const [label, size] of Object.entries(payloads)) {
    const payload = new Uint8Array(size); payload.fill(0x41);
    const total = buildSize(size); const frame = new Uint8Array(total);
    buildFrame(TYPE_REQUEST, 0, payload, frame, 0);
    for (const cs of [1, 16, 64, 256, 1024, 4096, Number.MAX_SAFE_INTEGER]) {
      const csLabel = cs === Number.MAX_SAFE_INTEGER ? "full" : String(cs);
      const actualCs = cs === Number.MAX_SAFE_INTEGER ? frame.length : cs;
      const chunks: Uint8Array[] = [];
      for (let i = 0; i < frame.length; i += actualCs) chunks.push(frame.subarray(i, Math.min(i + actualCs, frame.length)));
      const runs = size > 16384 ? 100 : 500;
      for (let w = 0; w < 5; w++) { const a = new FrameAssembler(); for (const c of chunks) a.push(c); }
      const start = performance.now();
      for (let n = 0; n < runs; n++) { const a = new FrameAssembler(); for (const c of chunks) a.push(c); }
      const ms = performance.now() - start;
      const tb = frame.length * runs;
      r.push({ name: `FrameAssembler ${label}(${size}B) chunk=${csLabel}`, category: "assembler", ops: runs, durationMs: Math.round(ms * 100) / 100, opsPerSec: Math.round((runs / ms) * 1000), bytesProcessed: tb, bytesPerSec: Math.round(tb / (ms / 1000)), extra: { payloadSize: size, chunkSize: csLabel === "full" ? frame.length : actualCs, numChunks: chunks.length } });
    }
  }
  return r;
}

// B. Compression
function benchCompression(): BenchResult[] {
  const r: BenchResult[] = [];
  for (const { name, obj } of MCP) {
    const jsonStr = JSON.stringify(obj);
    const jsonBytes = new TextEncoder().encode(jsonStr).length;
    const runs = 1000;
    const start = performance.now();
    for (let i = 0; i < runs; i++) compressValue(obj);
    const ms = performance.now() - start;
    const c = compressValue(obj); const cb = c.length;
    const ratio = (cb / jsonBytes * 100).toFixed(1);
    r.push({ name: `Compress ${name}`, category: "compression", ops: runs, durationMs: Math.round(ms * 100) / 100, opsPerSec: Math.round((runs / ms) * 1000), bytesProcessed: jsonBytes * runs, bytesPerSec: Math.round((jsonBytes * runs) / (ms / 1000)), extra: { objectName: name, jsonBytes, compressedBytes: cb, ratioPercent: parseFloat(ratio), savedBytes: jsonBytes - cb } });
  }
  return r;
}

// C. Hyb128
function benchHyb128(): BenchResult[] {
  const values = [0, 1, 31, 63, 64, 255, 1000, 65535, 65536, 100000, 1000000];
  const r: BenchResult[] = [];
  for (const v of values) {
    const buf = new Uint8Array(11);
    const start = performance.now();
    for (let i = 0; i < 100_000; i++) encodeHyb128(v, buf, 0);
    const ms = performance.now() - start;
    r.push({ name: `encodeHyb128(${v})`, category: "hyb128_encode", ops: 100_000, durationMs: Math.round(ms * 100) / 100, opsPerSec: Math.round((100_000 / ms) * 1000), bytesProcessed: 0, bytesPerSec: 0, extra: { value: v, mode: v <= 63 ? "00" : v <= 65535 ? "10" : "11" } });
  }
  for (const v of values) {
    const buf = new Uint8Array(11);
    const len = encodeHyb128(v, buf, 0);
    const enc = buf.subarray(0, len);
    const start = performance.now();
    for (let i = 0; i < 100_000; i++) decodeHyb128(enc, 0);
    const ms = performance.now() - start;
    r.push({ name: `decodeHyb128(${v})`, category: "hyb128_decode", ops: 100_000, durationMs: Math.round(ms * 100) / 100, opsPerSec: Math.round((100_000 / ms) * 1000), bytesProcessed: 0, bytesPerSec: 0, extra: { value: v, headerBytes: len } });
  }
  return r;
}

// D. Dict
function benchDict(): BenchResult[] {
  const keys = ["tool", "arguments", "result", "error", "id", "name", "description", "content", "text", "type", "method", "params", "jsonrpc", "data", "code", "message"];
  const start = performance.now();
  for (let i = 0; i < 1_000_000; i++) lookupDictId(keys[i % keys.length]);
  const ms = performance.now() - start;
  return [{ name: "dict_lookup O(1)", category: "dict", ops: 1_000_000, durationMs: Math.round(ms * 100) / 100, opsPerSec: Math.round((1_000_000 / ms) * 1000), bytesProcessed: 0, bytesPerSec: 0, extra: { totalKeys: keys.length } }];
}
// Part 2: bench functions E-H + main runner
// This will be concatenated with Part 1

// E. Encode: JSON.stringify vs compressValue
function benchEncode(): BenchResult[] {
  const r: BenchResult[] = [];
  for (const { name, obj } of MCP) {
    const jsonStr = JSON.stringify(obj);
    const jsonBytes = new TextEncoder().encode(jsonStr).length;
    const compressed = compressValue(obj);
    for (let w = 0; w < 50; w++) JSON.stringify(obj);
    const t0 = performance.now();
    for (let i = 0; i < 5000; i++) JSON.stringify(obj);
    const jMs = performance.now() - t0;
    const jOps = Math.round((5000 / jMs) * 1000);
    for (let w = 0; w < 50; w++) compressValue(obj);
    const t1 = performance.now();
    for (let i = 0; i < 5000; i++) compressValue(obj);
    const lMs = performance.now() - t1;
    const lOps = Math.round((5000 / lMs) * 1000);
    r.push({ name: `Encode JSON.stringify ${name}`, category: "json_encode", ops: 5000, durationMs: Math.round(jMs * 100) / 100, opsPerSec: jOps, bytesProcessed: jsonBytes * 5000, bytesPerSec: Math.round((jsonBytes * 5000) / (jMs / 1000)), extra: { objectName: name, jsonBytes } });
    r.push({ name: `Encode compressValue ${name}`, category: "lumen_encode", ops: 5000, durationMs: Math.round(lMs * 100) / 100, opsPerSec: lOps, bytesProcessed: compressed.length * 5000, bytesPerSec: Math.round((compressed.length * 5000) / (lMs / 1000)), extra: { objectName: name, compressedBytes: compressed.length, speedupVsJson: Math.round((lOps / jOps) * 100) / 100 } });
  }
  return r;
}

// F. Decode: JSON.parse vs decompressValue
function benchDecode(): BenchResult[] {
  const prepared = MCP.map(t => ({ ...t, jsonStr: JSON.stringify(t.obj), compressed: compressValue(t.obj) }));
  const r: BenchResult[] = [];
  for (const { name, jsonStr, compressed } of prepared) {
    const jsonBytes = new TextEncoder().encode(jsonStr).length;
    for (let w = 0; w < 50; w++) JSON.parse(jsonStr);
    const t0 = performance.now();
    for (let i = 0; i < 5000; i++) JSON.parse(jsonStr);
    const jMs = performance.now() - t0;
    const jOps = Math.round((5000 / jMs) * 1000);
    for (let w = 0; w < 50; w++) decompressValue(compressed);
    const t1 = performance.now();
    for (let i = 0; i < 5000; i++) decompressValue(compressed);
    const lMs = performance.now() - t1;
    const lOps = Math.round((5000 / lMs) * 1000);
    r.push({ name: `Decode JSON.parse ${name}`, category: "json_decode", ops: 5000, durationMs: Math.round(jMs * 100) / 100, opsPerSec: jOps, bytesProcessed: jsonBytes * 5000, bytesPerSec: Math.round((jsonBytes * 5000) / (jMs / 1000)), extra: { objectName: name, jsonBytes } });
    r.push({ name: `Decode decompressValue ${name}`, category: "lumen_decode", ops: 5000, durationMs: Math.round(lMs * 100) / 100, opsPerSec: lOps, bytesProcessed: compressed.length * 5000, bytesPerSec: Math.round((compressed.length * 5000) / (lMs / 1000)), extra: { objectName: name, compressedBytes: compressed.length, speedupVsJson: Math.round((lOps / jOps) * 100) / 100 } });
  }
  return r;
}

// G. Round-trip: JSON vs LUMEN
function benchRoundtrip(): BenchResult[] {
  const r: BenchResult[] = [];
  for (const { name, obj } of MCP) {
    const jsonStr = JSON.stringify(obj);
    const jsonBytes = new TextEncoder().encode(jsonStr).length;
    const compressed = compressValue(obj);
    for (let w = 0; w < 50; w++) { JSON.parse(JSON.stringify(obj)); }
    const t0 = performance.now();
    for (let i = 0; i < 5000; i++) { JSON.parse(JSON.stringify(obj)); }
    const jMs = performance.now() - t0;
    const jOps = Math.round((5000 / jMs) * 1000);
    for (let w = 0; w < 50; w++) { decompressValue(compressValue(obj)); }
    const t1 = performance.now();
    for (let i = 0; i < 5000; i++) { decompressValue(compressValue(obj)); }
    const lMs = performance.now() - t1;
    const lOps = Math.round((5000 / lMs) * 1000);
    r.push({ name: `Roundtrip JSON ${name}`, category: "json_roundtrip", ops: 5000, durationMs: Math.round(jMs * 100) / 100, opsPerSec: jOps, bytesProcessed: jsonBytes * 2 * 5000, bytesPerSec: Math.round((jsonBytes * 2 * 5000) / (jMs / 1000)), extra: { objectName: name, jsonBytes } });
    r.push({ name: `Roundtrip LUMEN ${name}`, category: "lumen_roundtrip", ops: 5000, durationMs: Math.round(lMs * 100) / 100, opsPerSec: lOps, bytesProcessed: compressed.length * 2 * 5000, bytesPerSec: Math.round((compressed.length * 2 * 5000) / (lMs / 1000)), extra: { objectName: name, compressedBytes: compressed.length, speedupVsJson: Math.round((lOps / jOps) * 100) / 100 } });
  }
  return r;
}

// H. Framing: Content-Length vs Hyb128 header parse
function benchFraming(): BenchResult[] {
  const r: BenchResult[] = [];
  function parseCL(line: string): number | null {
    const p = "Content-Length: ";
    if (!line.startsWith(p)) return null;
    const end = line.indexOf("\r\n", p.length);
    if (end === -1) return null;
    return parseInt(line.substring(p.length, end), 10);
  }
  const testVals = [0, 42, 255, 1024, 65535, 65536, 100000, 1000000];
  for (const v of testVals) {
    const cl = `Content-Length: ${v}\r\n\r\n`;
    for (let w = 0; w < 100; w++) parseCL(cl);
    const start = performance.now();
    for (let i = 0; i < 500_000; i++) parseCL(cl);
    const ms = performance.now() - start;
    r.push({ name: `Framing Content-Length(${v})`, category: "framing_cl", ops: 500_000, durationMs: Math.round(ms * 100) / 100, opsPerSec: Math.round((500_000 / ms) * 1000), bytesProcessed: cl.length * 500_000, bytesPerSec: Math.round((cl.length * 500_000) / (ms / 1000)), extra: { headerValue: v, headerBytes: cl.length } });
  }
  for (const v of testVals) {
    const buf = new Uint8Array(11);
    const len = encodeHyb128(v, buf, 0);
    const enc = buf.subarray(0, len);
    for (let w = 0; w < 100; w++) decodeHyb128(enc, 0);
    const start = performance.now();
    for (let i = 0; i < 500_000; i++) decodeHyb128(enc, 0);
    const ms = performance.now() - start;
    r.push({ name: `Framing Hyb128(${v})`, category: "framing_hyb128", ops: 500_000, durationMs: Math.round(ms * 100) / 100, opsPerSec: Math.round((500_000 / ms) * 1000), bytesProcessed: enc.length * 500_000, bytesPerSec: Math.round((enc.length * 500_000) / (ms / 1000)), extra: { headerValue: v, headerBytes: enc.length } });
  }
  return r;
}

// Main
const report: BenchReport = {
  timestamp: new Date().toISOString(),
  platform: `${process.platform} ${process.arch}`,
  nodeVersion: process.version,
  results: [],
};

console.error("=== LUMEN Benchmark Suite ===");
console.error(`Platform: ${report.platform}  Node: ${report.nodeVersion}`);
console.error("");

console.error("A. FrameAssembler..."); report.results.push(...benchAssembler());
console.error("B. Compression...");   report.results.push(...benchCompression());
console.error("C. Hyb128...");         report.results.push(...benchHyb128());
console.error("D. Dict...");           report.results.push(...benchDict());
console.error("E. Encode...");         report.results.push(...benchEncode());
console.error("F. Decode...");         report.results.push(...benchDecode());
console.error("G. Roundtrip...");      report.results.push(...benchRoundtrip());
console.error("H. Framing...");        report.results.push(...benchFraming());

console.log(JSON.stringify(report, null, 2));
console.error(`\nDone. ${report.results.length} benchmarks.`);
