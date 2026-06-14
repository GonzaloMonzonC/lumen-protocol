/**
 * LUMEN compression via Rust FFI — drop-in replacement for `compress.ts`.
 *
 * Uses the native Rust `lumen.dll` (or `liblumen.so`/`liblumen.dylib`) via
 * koffi FFI.  On compress the Rust path calls `serde_json` + the Rust encoder;
 * on decompress it calls the Rust decoder + `serde_json`.  Benchmarks show
 * **4.2× faster compress** and parity decompress vs the pure-TS implementation.
 *
 * ## Requirements
 *
 * The Rust shared library must be present next to the package:
 *
 * ```
 * implementations/rust/target/release/lumen.dll    (Windows)
 * implementations/rust/target/release/liblumen.so  (Linux)
 * implementations/rust/target/release/liblumen.dylib (macOS)
 * ```
 *
 * If the library is not found the module throws a descriptive error at first
 * call (not at import time), so you can feature-detect with a try/catch.
 *
 * @module
 */

// eslint-disable-next-line @typescript-eslint/triple-slash-reference
/// <reference types="node" />

import { existsSync } from "node:fs";
import { join } from "node:path";
import { compressedSize as _compressedSize } from "./compress.js";

declare var __dirname: string;

// ═══ koffi — load via require for CJS/ESM interop ════════════════════════

interface KoffiHandle {
  load(path: string): KoffiLib;
  decode(ptr: unknown, type: unknown): unknown;
  pointer(name: string): unknown;
  array(name: string, len: number): unknown;
}

interface KoffiLib {
  func(signature: string): (...args: unknown[]) => unknown;
}

// eslint-disable-next-line @typescript-eslint/no-require-imports
const koffi = require("koffi") as KoffiHandle;

// ═══ Resolve DLL path ═════════════════════════════════════════════════════

const dllName =
  process.platform === "win32"
    ? "lumen.dll"
    : process.platform === "darwin"
      ? "liblumen.dylib"
      : "liblumen.so";

// Walk up from __dirname (dist/ or src/) to find the Rust build artefact
const dllPath = join(__dirname, "..", "..", "rust", "target", "release", dllName);

// ═══ Lazy-loaded FFI handle ════════════════════════════════════════════════

interface LumenLib {
  lumen_compress: (
    jsonPtr: Uint8Array,
    jsonLen: number,
    outPtr: Uint8Array,
    outLen: Uint8Array,
  ) => number;
  lumen_decompress: (
    dataPtr: Uint8Array,
    dataLen: number,
    outPtr: Uint8Array,
    outLen: Uint8Array,
  ) => number;
  lumen_free: (ptr: unknown, len: number) => void;
}

let _lib: LumenLib | null = null;
let _libError: string | null = null;

function getLib(): LumenLib {
  if (_lib) return _lib;
  if (_libError) throw new Error(_libError);

  try {
    if (!existsSync(dllPath)) {
      _libError = `LUMEN Rust library not found at ${dllPath}. Build it with: cd implementations/rust && cargo build --release`;
      throw new Error(_libError);
    }

    const lib = koffi.load(dllPath);

    const handle: LumenLib = {
      lumen_compress: lib.func(
        "int32_t lumen_compress(const uint8_t *json_ptr, size_t json_len, uint8_t **out_ptr, size_t *out_len)",
      ) as LumenLib["lumen_compress"],
      lumen_decompress: lib.func(
        "int32_t lumen_decompress(const uint8_t *data_ptr, size_t data_len, uint8_t **out_ptr, size_t *out_len)",
      ) as LumenLib["lumen_decompress"],
      lumen_free: lib.func("void lumen_free(uint8_t *ptr, size_t len)") as LumenLib["lumen_free"],
    };
    _lib = handle;
    return handle;
  } catch (e) {
    _libError = e instanceof Error ? e.message : String(e);
    throw e;
  }
}

// ═══ FFI helpers ════════════════════════════════════════════════════════════

/** Call lumen_compress and copy the result into a fresh Uint8Array. */
function ffiCompress(jsonBytes: Uint8Array): Uint8Array {
  const { lumen_compress, lumen_free } = getLib();

  const outPtr = new Uint8Array(8); // pointer placeholder (8 bytes on 64-bit)
  const outLen = new Uint8Array(8); // size_t placeholder
  const rc = lumen_compress(jsonBytes, jsonBytes.length, outPtr, outLen);
  if (rc !== 0) throw new Error("lumen_compress failed");

  const ptr = koffi.decode(outPtr, koffi.pointer("uint8_t *")) as unknown as bigint;
  const dv = new DataView(outLen.buffer, outLen.byteOffset, 8);
  const len = Number(dv.getBigUint64(0, true));

  const result = new Uint8Array(
    koffi.decode(ptr, koffi.array("uint8_t", len)) as Uint8Array,
  );
  lumen_free(ptr, len);
  return result;
}

/** Call lumen_decompress and copy the result into a fresh Uint8Array (JSON UTF-8). */
function ffiDecompress(data: Uint8Array): Uint8Array {
  const { lumen_decompress, lumen_free } = getLib();

  const outPtr = new Uint8Array(8);
  const outLen = new Uint8Array(8);
  const rc = lumen_decompress(data, data.length, outPtr, outLen);
  if (rc !== 0) throw new Error("lumen_decompress failed");

  const ptr = koffi.decode(outPtr, koffi.pointer("uint8_t *")) as unknown as bigint;
  const dv = new DataView(outLen.buffer, outLen.byteOffset, 8);
  const len = Number(dv.getBigUint64(0, true));

  const result = new Uint8Array(
    koffi.decode(ptr, koffi.array("uint8_t", len)) as Uint8Array,
  );
  lumen_free(ptr, len);
  return result;
}

// ═══ Public API (same signatures as compress.ts) ═══════════════════════════

const encoder = new TextEncoder();
const decoder = new TextDecoder();

/**
 * Compress a JSON-compatible value into LUMEN compact binary.
 *
 * Uses the Rust native encoder under the hood — typically 4× faster than
 * the pure-TS implementation for complex payloads.
 */
export function compressValue(value: unknown): Uint8Array {
  const json = JSON.stringify(value);
  const jsonBytes = encoder.encode(json);
  return ffiCompress(jsonBytes);
}

/**
 * Compress a JSON-compatible value, appending to an existing `chunks` array.
 *
 * Because the Rust FFI produces a single contiguous buffer, this simply
 * calls `compressValue` and pushes the result as one chunk.
 */
export function compressInto(value: unknown, chunks: Uint8Array[]): void {
  chunks.push(compressValue(value));
}

/**
 * Decompress LUMEN compact binary back into a JSON-compatible value.
 *
 * Uses the Rust native decoder.  The Rust library returns a JSON string
 * which is then parsed with `JSON.parse`.
 */
export function decompressValue(data: Uint8Array): unknown {
  const jsonBytes = ffiDecompress(data);
  const json = decoder.decode(jsonBytes);
  return JSON.parse(json);
}

/**
 * Estimate the compressed size in bytes.
 *
 * Delegates to the pure-TS implementation — this is an estimation-only
 * function and the Rust FFI offers no advantage here.
 */
export { _compressedSize as compressedSize };
