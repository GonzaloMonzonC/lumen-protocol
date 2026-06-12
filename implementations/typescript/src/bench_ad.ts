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
