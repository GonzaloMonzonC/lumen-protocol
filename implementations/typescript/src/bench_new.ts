/**
 * LUMEN Benchmark Harness — expanded with JSON-RPC comparable benchmarks.
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
