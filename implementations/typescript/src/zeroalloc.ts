/**
 * Zero-Allocation Decompressor — "Vía 1" of the GC-pressure escape plan.
 *
 * A drop-in replacement for `decompressValue()` that produces the *same*
 * output but allocates **nothing intermediate**. Only the final result
 * objects/arrays/strings are created — everything else is reused across calls.
 *
 * ## What the naive `decompressValue` allocates (and we eliminate)
 *
 * | Naive decoder                            | Zero-alloc replacement                |
 * |------------------------------------------|---------------------------------------|
 * | `new TextDecoder()` per raw string       | one module-level shared decoder       |
 * | `decodeHyb128()` → `{ value, headerLen }`| inline read into instance fields      |
 * | `new DataView()` per float               | one `DataView` per `decompress()` call|
 * | recursion (JS stack frames)              | iterative loop + pooled frame stack   |
 * | `new Int32Array([pos])` cursor           | a plain `this.offset` number          |
 *
 * The frame pool persists on the instance, so after the first call the only
 * heap growth is the decoded payload itself — matching `JSON.parse`.
 *
 * Reuse a single instance across many frames for best results:
 * ```ts
 * const dec = new ZeroAllocDecompressor();
 * for (const frame of frames) result = dec.decompress(frame);
 * ```
 */

import { resolveDictId, ID_RAW, STATIC_MAX } from "./dict.js";

// ═══ Value tags (mirror compress.ts) ════════════════════════════════════════

const TAG_NULL = 0xe0;
const TAG_BOOL = 0xe1;
const TAG_FLOAT = 0xe2;
const TAG_INT = 0xe3;
const TAG_STR_DICT = 0xe4;
const TAG_STR_RAW = 0xe5;
const TAG_ARRAY = 0xe6;
const TAG_OBJECT = 0xe7;

// Hyb128 mode bits
const MODE_MASK = 0xc0;
const SHORT_MASK = 0x3f;
const MODE_SHORT = 0x00;
const MODE_U16 = 0x80;
const MODE_U32 = 0xc0;

// Safety cap on container element counts (matches naive decoder).
const MAX_COUNT = 1024;

// One shared decoder for the whole module — never re-allocated.
const SHARED_DECODER = new TextDecoder("utf-8", { fatal: true });

/** A reusable parse-stack frame. Pooled and mutated in place. */
interface Frame {
  isObject: boolean;
  container: unknown[] | Record<string, unknown>;
  remaining: number;
  pendingKey: string | null;
  idx: number;
}

export class ZeroAllocDecompressor {
  private data!: Uint8Array;
  private view!: DataView;
  private offset = 0;
  private end = 0;

  // Pooled frame stack — persists across calls, grows only if nesting deepens.
  private stack: Frame[] = [];
  private sp = 0;

  // Scratch holder for the root value (1-slot array reused every call).
  private readonly rootHolder: unknown[] = [undefined];

  /**
   * Decompress LUMEN compact binary into a JSON-compatible value.
   * Returns `null` if the input is malformed.
   */
  decompress(data: Uint8Array): unknown {
    this.data = data;
    this.view = new DataView(data.buffer, data.byteOffset, data.byteLength);
    this.offset = 0;
    this.end = data.length;
    this.sp = 0;
    this.rootHolder[0] = undefined;

    // Seed with a synthetic root frame expecting exactly one value.
    this.pushFrame(false, this.rootHolder, 1, null);

    while (this.sp > 0) {
      const top = this.stack[this.sp - 1];

      // Container fully populated → pop and let parent receive it.
      if (top.remaining <= 0) {
        this.sp--;
        continue;
      }

      // Object expecting a key first.
      if (top.isObject && top.pendingKey === null) {
        const key = this.readKey();
        if (key === null) {
          // Malformed/unsupported key — abort.
          return null;
        }
        top.pendingKey = key;
        continue;
      }

      // Read a value.
      if (this.offset >= this.end) break;
      const tag = this.data[this.offset++];

      switch (tag) {
        case TAG_NULL:
          this.attach(top, null);
          break;

        case TAG_BOOL: {
          if (this.offset >= this.end) return null;
          this.attach(top, this.data[this.offset++] !== 0);
          break;
        }

        case TAG_FLOAT: {
          if (this.offset + 8 > this.end) return null;
          const f = this.view.getFloat64(this.offset, true);
          this.offset += 8;
          this.attach(top, f);
          break;
        }

        case TAG_INT: {
          const n = this.readLeb128();
          if (n === null) return null;
          this.attach(top, n);
          break;
        }

        case TAG_STR_DICT: {
          if (this.offset >= this.end) return null;
          // resolveDictId returns a *shared* reference — no alloc.
          this.attach(top, resolveDictId(this.data[this.offset++]));
          break;
        }

        case TAG_STR_RAW: {
          const s = this.readRawString();
          if (s === null) return null;
          this.attach(top, s);
          break;
        }

        case TAG_ARRAY: {
          const count = this.readHyb128();
          if (count === null) return null;
          const n = count > MAX_COUNT ? MAX_COUNT : count;
          const arr = new Array<unknown>(n);
          this.attach(top, arr);
          this.pushFrame(false, arr, n, null);
          break;
        }

        case TAG_OBJECT: {
          const count = this.readHyb128();
          if (count === null) return null;
          const n = count > MAX_COUNT ? MAX_COUNT : count;
          const obj: Record<string, unknown> = {};
          this.attach(top, obj);
          this.pushFrame(true, obj, n, null);
          break;
        }

        default:
          // Unknown tag — malformed.
          return null;
      }
    }

    return this.rootHolder[0];
  }

  // ── Internals ──────────────────────────────────────────────────────────

  /** Attach a finished value to the current top frame. */
  private attach(top: Frame, value: unknown): void {
    if (top.isObject) {
      (top.container as Record<string, unknown>)[top.pendingKey as string] =
        value;
      top.pendingKey = null;
    } else {
      (top.container as unknown[])[top.idx++] = value;
    }
    top.remaining--;
  }

  /** Push a frame, reusing a pooled object if available. */
  private pushFrame(
    isObject: boolean,
    container: unknown[] | Record<string, unknown>,
    remaining: number,
    pendingKey: string | null,
  ): void {
    let frame = this.stack[this.sp];
    if (frame === undefined) {
      frame = { isObject, container, remaining, pendingKey, idx: 0 };
      this.stack[this.sp] = frame;
    } else {
      frame.isObject = isObject;
      frame.container = container;
      frame.remaining = remaining;
      frame.pendingKey = pendingKey;
      frame.idx = 0;
    }
    this.sp++;
  }

  /** Inline Hyb128 decode — advances offset, returns value (no alloc). */
  private readHyb128(): number | null {
    if (this.offset >= this.end) return null;
    const first = this.data[this.offset];
    const mode = first & MODE_MASK;

    if (mode === MODE_SHORT) {
      this.offset += 1;
      return first & SHORT_MASK;
    }
    if (mode === MODE_U16) {
      if (this.offset + 3 > this.end) return null;
      const v = this.data[this.offset + 1] | (this.data[this.offset + 2] << 8);
      this.offset += 3;
      return v;
    }
    if (mode === MODE_U32) {
      if (this.offset + 5 > this.end) return null;
      const v =
        (this.data[this.offset + 1] |
          (this.data[this.offset + 2] << 8) |
          (this.data[this.offset + 3] << 16) |
          (this.data[this.offset + 4] << 24)) >>>
        0;
      this.offset += 5;
      return v;
    }

    // Mode 01: LEB128 continuation.
    let value = 0;
    let shift = 0;
    let i = this.offset + 1;
    for (let n = 0; n < 10; n++) {
      if (i >= this.end) return null;
      const byte = this.data[i++];
      value |= (byte & 0x7f) << shift;
      if ((byte & 0x80) === 0) {
        this.offset = i;
        return value >>> 0;
      }
      shift += 7;
      if (shift >= 64) return null;
    }
    return null;
  }

  /** Inline zigzag LEB128 decode for integers. */
  private readLeb128(): number | null {
    let u = 0;
    let shift = 0;
    for (let i = 0; i < 10; i++) {
      if (this.offset >= this.end) return null;
      const byte = this.data[this.offset++];
      u |= (byte & 0x7f) << shift;
      if ((byte & 0x80) === 0) {
        return (u >>> 1) ^ -(u & 1);
      }
      shift += 7;
      if (shift >= 64) return null;
    }
    return null;
  }

  /** Read a raw UTF-8 string value (after TAG_STR_RAW). */
  private readRawString(): string | null {
    const len = this.readHyb128();
    if (len === null) return null;
    if (this.offset + len > this.end) return null;
    const s = SHARED_DECODER.decode(
      this.data.subarray(this.offset, this.offset + len),
    );
    this.offset += len;
    return s;
  }

  /** Read an object key (dict ID, or raw UTF-8). */
  private readKey(): string | null {
    if (this.offset >= this.end) return null;
    const first = this.data[this.offset++];

    if (first === ID_RAW) {
      return this.readRawString();
    }
    if (first < STATIC_MAX) {
      // Shared reference from the static dictionary — no alloc.
      return resolveDictId(first);
    }
    // Session-range IDs not yet supported.
    return null;
  }
}

/**
 * Convenience one-shot decompress. For hot paths, prefer constructing a single
 * {@link ZeroAllocDecompressor} and reusing it to amortize the frame pool.
 */
const sharedDecompressor = new ZeroAllocDecompressor();
export function decompressValueZeroAlloc(data: Uint8Array): unknown {
  return sharedDecompressor.decompress(data);
}
