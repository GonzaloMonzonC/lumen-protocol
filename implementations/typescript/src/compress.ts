/**
 * Compact binary payload compression/decompression.
 *
 * Value tags:
 * ```
 * 0xE0 = NULL   0xE1 = BOOL   0xE2 = FLOAT (f64 LE)
 * 0xE3 = INT (zigzag LEB128)   0xE4 = STR_DICT (1B ID)
 * 0xE5 = STR_RAW               0xE6 = ARRAY       0xE7 = OBJECT
 * ```
 *
 * Keys inside objects: `0x00-0x7E` = dict ID, `0xFF` = raw UTF-8.
 */

/**
 * Estimate the compressed size of a JSON value in bytes.
 * Used for pre-allocation. May over- or under-estimate slightly;
 * the actual encoder handles both cases.
 */
export function compressedSize(value: unknown): number {
  // TODO: port from Rust (src/compress.rs)
  // Returns an estimate; actual compression may differ.
  throw new Error("compress.compressedSize: not yet implemented");
}

/**
 * Compress a JSON-compatible value into LUMEN compact binary.
 * Returns the compressed Buffer.
 */
export function compressValue(value: unknown): Buffer {
  // TODO: port from Rust (src/compress.rs)
  throw new Error("compress.compressValue: not yet implemented");
}

/**
 * Decompress LUMEN compact binary back into a JSON-compatible value.
 */
export function decompressValue(data: Buffer): unknown {
  // TODO: port from Rust (src/compress.rs)
  throw new Error("compress.decompressValue: not yet implemented");
}
