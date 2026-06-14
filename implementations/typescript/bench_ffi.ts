/**
 * Benchmark: Node/TS native vs Rust FFI for LUMEN compress/decompress.
 *
 * Usage: npx tsx bench_ffi.ts
 */
import * as path from 'node:path';
import * as fs from 'node:fs';
import { compressValue, decompressValue } from './src/compress.js';
import koffi from 'koffi';

// ── Load Rust DLL ──
const dllPath = path.resolve('../rust/target/release/lumen.dll');
if (!fs.existsSync(dllPath)) {
  console.error(`DLL not found: ${dllPath}`);
  process.exit(1);
}
const lib = koffi.load(dllPath);

const lumen_compress = lib.func(
  'int32_t lumen_compress(const uint8_t *json_ptr, size_t json_len, uint8_t **out_ptr, size_t *out_len)'
);
const lumen_decompress = lib.func(
  'int32_t lumen_decompress(const uint8_t *data_ptr, size_t data_len, uint8_t **out_ptr, size_t *out_len)'
);
const lumen_free = lib.func('void lumen_free(uint8_t *ptr, size_t len)');

// ── FFI wrappers ──
function ffiCompress(jsonBytes: Uint8Array): Uint8Array {
  const outPtr = Buffer.alloc(8);  // pointer placeholder
  const outLen = Buffer.alloc(8);  // size_t placeholder
  const rc = lumen_compress(jsonBytes, jsonBytes.length, outPtr, outLen);
  if (rc !== 0) throw new Error(`lumen_compress failed: ${rc}`);
  const ptr = koffi.decode(outPtr, koffi.pointer('uint8_t *')) as unknown as bigint;
  const len = Number(outLen.readBigUInt64LE(0));
  const result = new Uint8Array(koffi.decode(ptr, koffi.array('uint8_t', len)) as Uint8Array);
  lumen_free(ptr, len);
  return result;
}

function ffiDecompress(data: Uint8Array): Uint8Array {
  const outPtr = Buffer.alloc(8);
  const outLen = Buffer.alloc(8);
  const rc = lumen_decompress(data, data.length, outPtr, outLen);
  if (rc !== 0) throw new Error(`lumen_decompress failed: ${rc}`);
  const ptr = koffi.decode(outPtr, koffi.pointer('uint8_t *')) as unknown as bigint;
  const len = Number(outLen.readBigUInt64LE(0));
  const result = new Uint8Array(koffi.decode(ptr, koffi.array('uint8_t', len)) as Uint8Array);
  lumen_free(ptr, len);
  return result;
}

// ── Benchmark helper ──
function bench(fn: (data: Uint8Array) => Uint8Array, data: Uint8Array, iters: number): number {
  // Warmup
  for (let i = 0; i < Math.min(iters / 5 | 0, 100); i++) fn(data);
  // Measure
  const t0 = performance.now();
  for (let i = 0; i < iters; i++) fn(data);
  const ms = performance.now() - t0;
  return (ms / iters) * 1000; // microseconds per call
}

// ── Fixtures (matching Python benchmark) ──
const smallVal = { jsonrpc: '2.0', id: 1, method: 'tools/list' };
const initVal = {
  jsonrpc: '2.0', id: 1, method: 'initialize',
  params: {
    protocolVersion: '2025-06-18',
    capabilities: { roots: { listChanged: true }, sampling: {} },
  },
};
const toolsVal = {
  jsonrpc: '2.0', id: 2, result: {
    tools: Array.from({ length: 20 }, (_, i) => ({
      name: `tool_${i}`,
      description: `Tool ${i} description here`,
      inputSchema: {
        type: 'object',
        properties: {
          query: { type: 'string', description: 'Search query' },
          limit: { type: 'integer', description: 'Max results' },
          verbose: { type: 'boolean' },
        },
      },
    })),
  },
};
const llmVal = {
  jsonrpc: '2.0', id: 3, result: {
    content: [{ type: 'text', text: "def hello():\n    print('Hello world')\n\ndef goodbye():\n    print('Bye')" }],
    model: 'claude-4',
    usage: { input_tokens: 150, output_tokens: 85 },
  },
};

type Case = [string, object, Uint8Array, number];
const cases: Case[] = [
  ['MCP tools/list', smallVal, new TextEncoder().encode(JSON.stringify(smallVal)), 5000],
  ['MCP initialize', initVal, new TextEncoder().encode(JSON.stringify(initVal)), 5000],
  ['MCP tools x20', toolsVal, new TextEncoder().encode(JSON.stringify(toolsVal)), 1000],
  ['LLM response', llmVal, new TextEncoder().encode(JSON.stringify(llmVal)), 2000],
];

// ── Run ──
console.log(`${'Payload'.padEnd(22)} ${'Op'.padStart(12)} ${'Native'.padStart(10)} ${'FFI'.padStart(10)} ${'Speedup'.padStart(8)}`);
console.log('-'.repeat(67));

let totNc = 0, totFc = 0, totNd = 0, totFd = 0;

for (const [label, val, jbytes, iters] of cases) {
  // Pre-compute the compressed binary (native) for decompress benchmarks
  const raw = compressValue(val);

  // Compress: native (includes JSON.parse) vs FFI (raw JSON bytes)
  const nc = bench((b) => compressValue(JSON.parse(new TextDecoder().decode(b))), jbytes, iters);
  const fc = bench(ffiCompress, jbytes, iters);

  // Decompress: native (direct) vs FFI (includes JSON.parse)
  const nd = bench((b) => { decompressValue(b); return b; }, raw, iters);
  const fd = bench((b) => { ffiDecompress(b); return b; }, raw, iters);

  console.log(
    `${label.padEnd(22)} ${'compress'.padStart(12)} ${nc.toFixed(1).padStart(9)}us ${fc.toFixed(1).padStart(9)}us ${(nc / fc).toFixed(1).padStart(7)}x`
  );
  console.log(
    `${label.padEnd(22)} ${'decompress'.padStart(12)} ${nd.toFixed(1).padStart(9)}us ${fd.toFixed(1).padStart(9)}us ${(nd / fd).toFixed(1).padStart(7)}x`
  );
  totNc += nc; totFc += fc; totNd += nd; totFd += fd;
}

console.log('-'.repeat(67));
console.log(
  `${'TOTAL'.padEnd(22)} ${'compress'.padStart(12)} ${totNc.toFixed(1).padStart(9)}us ${totFc.toFixed(1).padStart(9)}us ${(totNc / totFc).toFixed(1).padStart(7)}x`
);
console.log(
  `${'TOTAL'.padEnd(22)} ${'decompress'.padStart(12)} ${totNd.toFixed(1).padStart(9)}us ${totFd.toFixed(1).padStart(9)}us ${(totNd / totFd).toFixed(1).padStart(7)}x`
);
