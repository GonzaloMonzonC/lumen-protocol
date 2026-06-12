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
