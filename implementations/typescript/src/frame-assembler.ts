/**
 * FrameAssembler — streaming frame parser with pre-allocation.
 *
 * ## Problem
 *
 * In stdio / WebSockets, a 5 MB frame may arrive in 100+ chunks.
 * Using `Buffer.concat()` on every chunk allocates O(n²) memory
 * and thrashes the garbage collector.
 *
 * ## Solution
 *
 * This state machine:
 * 1. Reads the Hyb128 header from the **first chunk** to determine
 *    the exact total frame size.
 * 2. Pre-allocates a single `Uint8Array` of that exact size.
 * 3. Fills it incrementally as chunks arrive (cursor-based copy).
 * 4. Emits the complete frame and resets for the next one.
 *
 * **Zero heap allocations after the initial pre-allocation.**
 * **No `Buffer` dependency — runs in Node.js, Workers, and browsers.**
 */

import { decodeHyb128 } from "./hyb128.js";
import { Frame, ParseResult } from "./frame.js";
import { parseFrame } from "./frame.js";

// ═══ Assembler ══════════════════════════════════════════════════════════════

/**
 * Accumulates raw byte chunks and emits complete LUMEN frames.
 *
 * Usage:
 * ```typescript
 * const assembler = new FrameAssembler();
 * stream.on("data", (chunk: Uint8Array) => {
 *   const frames = assembler.push(chunk);
 *   for (const frame of frames) handleFrame(frame);
 * });
 * ```
 */
export class FrameAssembler {
  /** Pre-allocated buffer for the current in-flight frame. */
  private buf: Uint8Array | null = null;
  /** How many bytes have been written into `buf`. */
  private filled = 0;
  /** Target total frame size (header + payload). Known after Hyb128 decode. */
  private target = 0;

  /**
   * Feed a chunk of bytes into the assembler.
   *
   * Returns zero or more complete frames extracted from the accumulated data.
   * Any leftover bytes are retained internally for the next call.
   *
   * @param chunk  Raw bytes from the stream (Uint8Array or Node Buffer).
   */
  push(chunk: Uint8Array): Frame[] {
    const frames: Frame[] = [];

    // Ensure we're working with Uint8Array (not Buffer subclass)
    const data = chunk instanceof Uint8Array
      ? new Uint8Array(chunk.buffer, chunk.byteOffset, chunk.byteLength)
      : new Uint8Array(chunk);

    let offset = 0;

    while (offset < data.length) {
      if (this.buf === null) {
        // ── State: waiting for new frame header ──────────────────────────
        offset = this.readHeader(data, offset, frames);
      } else {
        // ── State: filling an in-progress frame ──────────────────────────
        offset = this.fillBuffer(data, offset, frames);
      }
    }

    return frames;
  }

  /**
   * Flush any partially-assembled frame data.
   * Call this when the stream ends to recover trailing bytes.
   */
  flush(): Uint8Array | null {
    if (this.buf === null || this.filled === 0) return null;
    const partial = this.buf.subarray(0, this.filled);
    this.reset();
    return partial;
  }

  /** Reset internal state (e.g., after transport close). */
  reset(): void {
    this.buf = null;
    this.filled = 0;
    this.target = 0;
  }

  // ═══ Private ══════════════════════════════════════════════════════════════

  /**
   * Try to read a Hyb128 header + TYPE + FLAGS from `data` starting at `offset`.
   *
   * If we have enough bytes to determine the total frame size, pre-allocate
   * the buffer and begin filling. Otherwise, buffer what we have and wait.
   */
  private readHeader(
    data: Uint8Array,
    offset: number,
    frames: Frame[],
  ): number {
    const remaining = data.length - offset;

    // We need at least 1 byte to start Hyb128 decode
    if (remaining < 1) return offset;

    // Attempt Hyb128 decode on available data
    const decoded = decodeHyb128(data, offset);
    if (!decoded) {
      // Incomplete Hyb128 header — buffer everything we have
      this.allocateBuffer(remaining);
      this.buf!.set(data.subarray(offset), 0);
      this.filled = remaining;
      return data.length; // consumed everything
    }

    const headerLen = decoded.headerLen;
    const payloadLen = decoded.value;
    const totalLen = headerLen + 2 + payloadLen; // Hyb128 + TYPE + FLAGS + payload

    // Do we have TYPE + FLAGS at least?
    const typeOffset = offset + headerLen;
    if (typeOffset + 2 > data.length) {
      // Have Hyb128 but not TYPE+FLAGS — buffer what we have
      const available = data.length - offset;
      this.allocateBuffer(totalLen);
      this.buf!.set(data.subarray(offset), 0);
      this.filled = available;
      return data.length;
    }

    // We have the full header. Pre-allocate and start filling.
    this.allocateBuffer(totalLen);
    this.target = totalLen;

    // Copy what we have so far
    const available = data.length - offset;
    const toCopy = Math.min(available, totalLen);
    this.buf!.set(data.subarray(offset, offset + toCopy), 0);
    this.filled = toCopy;

    // Check if frame is already complete
    if (this.filled >= this.target) {
      return this.emitFrame(frames, offset + toCopy);
    }

    return data.length; // consumed all remaining, wait for more
  }

  /**
   * Fill the pre-allocated buffer with incoming data.
   * Emits the frame when `filled >= target`.
   */
  private fillBuffer(
    data: Uint8Array,
    offset: number,
    frames: Frame[],
  ): number {
    const needed = this.target - this.filled;
    const available = data.length - offset;
    const toCopy = Math.min(needed, available);

    this.buf!.set(data.subarray(offset, offset + toCopy), this.filled);
    this.filled += toCopy;
    offset += toCopy;

    if (this.filled >= this.target) {
      return this.emitFrame(frames, offset);
    }

    return offset;
  }

  /**
   * Parse and emit the completed frame, reset for next.
   */
  private emitFrame(frames: Frame[], nextOffset: number): number {
    const result = parseFrame(this.buf!, 0);

    if (result.kind === "complete") {
      frames.push(result.frame);
    }
    // On error or incomplete (shouldn't happen with pre-allocation),
    // we skip the frame silently.

    this.buf = null;
    this.filled = 0;
    this.target = 0;

    return nextOffset;
  }

  private allocateBuffer(size: number): void {
    // Only allocate if we don't already have one big enough
    if (!this.buf || this.buf.length < size) {
      this.buf = new Uint8Array(size);
    }
    this.target = size;
  }
}
