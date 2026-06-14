/**
 * LUMEN Level 2 — Shared Memory (Zero-Copy) Transport via Rust FFI.
 *
 * Uses the native Rust `lumen.dll` (or `liblumen.so`/`liblumen.dylib`) via
 * koffi FFI to provide zero-copy inter-process communication through
 * shared memory ring buffers.
 *
 * ## Architecture
 *
 * One shared memory region contains two unidirectional lock-free SPSC ring
 * buffers:
 *
 *   Ring A: Client → Server
 *   Ring B: Server → Client
 *
 * Each ring is length-prefixed (4-byte LE + payload).  The FFI layer
 * exposes five C functions:
 *
 *   lumen_shm_create(name, size)  → opaque handle  (server)
 *   lumen_shm_open(name, size)    → opaque handle  (client)
 *   lumen_shm_write_frame(h, side, data) → 0/-1
 *   lumen_shm_read_frame(h, side, buf)   → payload | null
 *   lumen_shm_close(h)
 *
 * ## Requirements
 *
 * The Rust shared library must be present:
 *
 * ```
 * implementations/rust/target/release/lumen.dll    (Windows)
 * implementations/rust/target/release/liblumen.so  (Linux)
 * implementations/rust/target/release/liblumen.dylib (macOS)
 * ```
 *
 * @module
 */

// eslint-disable-next-line @typescript-eslint/triple-slash-reference
/// <reference types="node" />

import { existsSync } from "node:fs";
import { join } from "node:path";

declare var __dirname: string;

// ═══ koffi — load via require for CJS/ESM interop ════════════════════════

interface KoffiHandle {
  load(path: string): KoffiLib;
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

const dllPath = join(__dirname, "..", "..", "rust", "target", "release", dllName);

// ═══ SHM FFI interface ════════════════════════════════════════════════════

interface ShmLib {
  lumen_shm_create: (
    namePtr: Uint8Array,
    nameLen: number,
    size: number,
  ) => unknown; // → *mut ShmOpaque (koffi external pointer)

  lumen_shm_open: (
    namePtr: Uint8Array,
    nameLen: number,
    size: number,
  ) => unknown;

  lumen_shm_write_frame: (
    handle: unknown,
    side: number,
    dataPtr: Uint8Array,
    dataLen: number,
  ) => number;

  lumen_shm_read_frame: (
    handle: unknown,
    side: number,
    bufPtr: Uint8Array,
    bufCap: number,
    outLenPtr: Uint8Array,
  ) => number;

  lumen_shm_close: (handle: unknown) => void;

  lumen_error_message: () => unknown; // *const c_char
}

let _lib: ShmLib | null = null;

function loadShmLib(): ShmLib {
  if (_lib) return _lib;
  if (!existsSync(dllPath)) {
    throw new Error(
      `LUMEN SHM FFI: native library not found at "${dllPath}". ` +
      `Build it with: cd implementations/rust && cargo build --release`,
    );
  }
  const lib = koffi.load(dllPath);
  _lib = {
    lumen_shm_create: lib.func(
      "void* lumen_shm_create(const uint8_t *name, unsigned int name_len, unsigned int size)",
    ) as ShmLib["lumen_shm_create"],
    lumen_shm_open: lib.func(
      "void* lumen_shm_open(const uint8_t *name, unsigned int name_len, unsigned int size)",
    ) as ShmLib["lumen_shm_open"],
    lumen_shm_write_frame: lib.func(
      "int32_t lumen_shm_write_frame(void *handle, uint8_t side, const uint8_t *data, unsigned int data_len)",
    ) as ShmLib["lumen_shm_write_frame"],
    lumen_shm_read_frame: lib.func(
      "int32_t lumen_shm_read_frame(void *handle, uint8_t side, uint8_t *buf, unsigned int buf_cap, unsigned int *out_len)",
    ) as ShmLib["lumen_shm_read_frame"],
    lumen_shm_close: lib.func(
      "void lumen_shm_close(void *handle)",
    ) as ShmLib["lumen_shm_close"],
    lumen_error_message: lib.func(
      "const char* lumen_error_message(void)",
    ) as ShmLib["lumen_error_message"],
  };
  return _lib;
}

// ═══ Ring side constants ══════════════════════════════════════════════════

/**
 * Ring A: Client writes, Server reads.
 */
export const RING_A = 0;

/**
 * Ring B: Server writes, Client reads.
 */
export const RING_B = 1;

/** Default region size (512 KiB). */
export const DEFAULT_SHM_SIZE = 524288;

// ═══ ShmTransportFFI — Zero-copy transport for Node.js ════════════════════

/**
 * Zero-copy shared memory transport backed by the native Rust LUMEN library.
 *
 * ## Usage (server)
 *
 * ```ts
 * const transport = ShmTransportFFI.createServer("/lumen-shm-1234");
 * transport.writeFrame(Buffer.from("hello"));       // Ring B → Client
 * const payload = transport.readFrame();             // Ring A ← Client
 * transport.close();
 * ```
 *
 * ## Usage (client)
 *
 * ```ts
 * const transport = ShmTransportFFI.openClient("/lumen-shm-1234");
 * transport.writeFrame(Buffer.from("request"));      // Ring A → Server
 * const response = transport.readFrame();             // Ring B ← Server
 * transport.close();
 * ```
 */
export class ShmTransportFFI {
  private handle: unknown;
  private lib: ShmLib;
  /** Ring we write to */
  private writeSide: number;
  /** Ring we read from */
  private readSide: number;

  private constructor(
    handle: unknown,
    lib: ShmLib,
    writeSide: number,
    readSide: number,
  ) {
    this.handle = handle;
    this.lib = lib;
    this.writeSide = writeSide;
    this.readSide = readSide;
  }

  // ── Factory methods ──────────────────────────────────────────────

  /**
   * Create a new shared memory region (server side).
   *
   * The server writes to Ring B and reads from Ring A.
   */
  static createServer(name: string, size: number = DEFAULT_SHM_SIZE): ShmTransportFFI {
    const lib = loadShmLib();
    const nameBuf = new TextEncoder().encode(name);
    const handle = lib.lumen_shm_create(nameBuf, nameBuf.length, size);
    if (!handle) {
      throw new Error(`lumen_shm_create failed for "${name}"`);
    }
    return new ShmTransportFFI(handle, lib, RING_B, RING_A);
  }

  /**
   * Open an existing shared memory region (client side).
   *
   * The client writes to Ring A and reads from Ring B.
   */
  static openClient(name: string, size: number = DEFAULT_SHM_SIZE): ShmTransportFFI {
    const lib = loadShmLib();
    const nameBuf = new TextEncoder().encode(name);
    const handle = lib.lumen_shm_open(nameBuf, nameBuf.length, size);
    if (!handle) {
      throw new Error(`lumen_shm_open failed for "${name}"`);
    }
    return new ShmTransportFFI(handle, lib, RING_A, RING_B);
  }

  // ── Write ────────────────────────────────────────────────────────

  /**
   * Write a length-prefixed frame to the outgoing ring.
   *
   * This is non-blocking — the ring buffer is lock-free and the write
   * will spin briefly if the ring is full.
   */
  writeFrame(data: Uint8Array): void {
    const rc = this.lib.lumen_shm_write_frame(
      this.handle,
      this.writeSide,
      data,
      data.length,
    );
    if (rc !== 0) {
      throw new Error("lumen_shm_write_frame failed: ring full or invalid handle");
    }
  }

  // ── Read ─────────────────────────────────────────────────────────

  /**
   * Read a length-prefixed frame from the incoming ring.
   *
   * Returns `null` if no complete frame is available.
   * Returns a `Buffer` with the frame payload on success.
   *
   * Maximum frame size is 64 KiB by default (configurable via `maxFrameSize`).
   */
  readFrame(maxFrameSize: number = 65536): Buffer | null {
    const buf = Buffer.allocUnsafe(maxFrameSize);
    const outLenBuf = Buffer.allocUnsafe(4); // u32 written here

    const rc = this.lib.lumen_shm_read_frame(
      this.handle,
      this.readSide,
      buf,
      maxFrameSize,
      outLenBuf,
    );

    if (rc === 0) {
      const actualLen = outLenBuf.readUInt32LE(0);
      return buf.slice(0, actualLen);
    }
    return null;
  }

  // ── Lifecycle ────────────────────────────────────────────────────

  /**
   * Close the shared memory region and free the native handle.
   *
   * After calling this, the transport must not be used.
   * On the server side this also unlinks the named region.
   */
  close(): void {
    if (this.handle) {
      this.lib.lumen_shm_close(this.handle);
      this.handle = null;
    }
  }
}
