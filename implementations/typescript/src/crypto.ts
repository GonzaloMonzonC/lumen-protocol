/**
 * LUMEN Wire Encryption — ChaCha20-Poly1305 AEAD + X25519 key exchange.
 *
 * Uses the Web Crypto API (available in Node.js 16+, Deno, and browsers).
 * Mirrors the Rust `crypto.rs` module exactly for cross-platform compatibility.
 *
 * ## Encrypted payload layout
 *
 * ```
 * [NONCE:12B] [CIPHERTEXT:N bytes] [TAG:16B]
 * ```
 *
 * ## Nonce construction
 *
 * Nonce = [counter: u64 LE][zeros: 4B] = 12 bytes
 * Counter is per-direction, monotonically increasing.
 *
 * ## Key Exchange (X25519)
 *
 * 1. Each side generates an X25519 keypair
 * 2. Public keys are exchanged via PROBE/PROBE_ACK (base64-encoded)
 * 3. Shared secret = X25519(own_secret, peer_public)
 * 4. TWO independent keys derived via HKDF-SHA256:
 *    `lumen-c2s-key` (client→server) and `lumen-s2c-key` (server→client).
 *    The initiator sends with c2s and receives with s2c; the responder
 *    does the reverse. This prevents catastrophic (key, nonce) reuse.
 */

import {
  buildFrame,
  buildSize,
  FLAG_ENCRYPTED,
} from "./frame.js";

// ═══ Constants ══════════════════════════════════════════════════════════════

export const NONCE_SIZE = 12;
export const TAG_SIZE = 16;
export const PUBLIC_KEY_SIZE = 32;
export const SECRET_KEY_SIZE = 32;
export const ENCRYPTION_OVERHEAD = NONCE_SIZE + TAG_SIZE;

const AEAD_ALGORITHM = "ChaCha20-Poly1305";
const HKDF_INFO_C2S = new TextEncoder().encode("lumen-c2s-key");
const HKDF_INFO_S2C = new TextEncoder().encode("lumen-s2c-key");
const WINDOW_SIZE = 64; // anti-replay bitmap width

/** Narrow Uint8Array to BufferSource for Web Crypto API. */
function asBufferSource(data: Uint8Array): BufferSource {
  return data as unknown as BufferSource;
}

// ═══ Role ═══════════════════════════════════════════════════════════════════

export enum Role {
  Initiator = "initiator",
  Responder = "responder",
}

// ═══ Keypair ════════════════════════════════════════════════════════════════

export interface Keypair {
  secretKey: Uint8Array;
  publicKey: Uint8Array;
}

export async function generateKeypair(): Promise<Keypair> {
  const kp = await crypto.subtle.generateKey(
    "X25519", true, ["deriveBits"]
  ) as CryptoKeyPair;
  const publicKey = new Uint8Array(await crypto.subtle.exportKey("raw", kp.publicKey));
  const secretKey = new Uint8Array(await crypto.subtle.exportKey("raw", kp.privateKey));
  return { secretKey, publicKey };
}

export async function deriveSharedSecret(
  secretKey: Uint8Array, peerPublicKey: Uint8Array
): Promise<Uint8Array> {
  const ourKey = await crypto.subtle.importKey(
    "raw", asBufferSource(secretKey), "X25519", false, ["deriveBits"]
  );
  const peerKey = await crypto.subtle.importKey(
    "raw", asBufferSource(peerPublicKey), "X25519", false, []
  );
  const sharedBits = await crypto.subtle.deriveBits(
    { name: "X25519", public: peerKey }, ourKey, 256
  );
  return new Uint8Array(sharedBits);
}

/** Derive a single 256-bit key from shared secret via HKDF. */
async function hkdfExpand(sharedSecret: Uint8Array, info: Uint8Array): Promise<CryptoKey> {
  const hkdfKey = await crypto.subtle.importKey(
    "raw", asBufferSource(sharedSecret), "HKDF", false, ["deriveBits"]
  );
  const derived = await crypto.subtle.deriveBits(
    { name: "HKDF", hash: "SHA-256", salt: asBufferSource(new Uint8Array(0)), info: asBufferSource(info) },
    hkdfKey, 256
  );
  return crypto.subtle.importKey(
    "raw", derived as BufferSource, { name: AEAD_ALGORITHM }, false,
    ["encrypt", "decrypt"]
  );
}

// ═══ Cipher ═════════════════════════════════════════════════════════════════

export class Cipher {
  private sendKey!: CryptoKey;
  private recvKey!: CryptoKey;
  private sendCounter: bigint = BigInt(0);
  // Anti-replay sliding window
  private recvWindow: bigint = BigInt(0);
  private recvBitmap: bigint = BigInt(0);
  private _initialized = false;

  constructor() {}

  async init(sharedSecret: Uint8Array, role: Role): Promise<void> {
    const [c2sKey, s2cKey] = await Promise.all([
      hkdfExpand(sharedSecret, HKDF_INFO_C2S),
      hkdfExpand(sharedSecret, HKDF_INFO_S2C),
    ]);
    if (role === Role.Initiator) {
      this.sendKey = c2sKey;
      this.recvKey = s2cKey;
    } else {
      this.sendKey = s2cKey;
      this.recvKey = c2sKey;
    }
    this.sendCounter = BigInt(0);
    this.recvWindow = BigInt(0);
    this.recvBitmap = BigInt(0);
    this._initialized = true;
  }

  get initialized(): boolean { return this._initialized; }

  private static makeNonce(counter: bigint): Uint8Array {
    const nonce = new Uint8Array(NONCE_SIZE);
    new DataView(nonce.buffer).setBigUint64(0, counter, true);
    return nonce;
  }

  async encrypt(plaintext: Uint8Array): Promise<Uint8Array> {
    if (!this._initialized) throw new Error("Cipher not initialized");
    const nonce = Cipher.makeNonce(this.sendCounter);
    this.sendCounter += BigInt(1);
    const ciphertext = new Uint8Array(
      await crypto.subtle.encrypt(
        { name: AEAD_ALGORITHM, nonce, additionalData: new Uint8Array(0) } as any,
        this.sendKey, asBufferSource(plaintext)
      )
    );
    const out = new Uint8Array(NONCE_SIZE + ciphertext.length);
    out.set(nonce, 0);
    out.set(ciphertext, NONCE_SIZE);
    return out;
  }

  async decrypt(encrypted: Uint8Array): Promise<Uint8Array> {
    if (!this._initialized) throw new Error("Cipher not initialized");
    if (encrypted.length < NONCE_SIZE + TAG_SIZE) {
      throw new DecryptError("encrypted payload too short");
    }
    const nonce = encrypted.slice(0, NONCE_SIZE);
    const ciphertext = encrypted.slice(NONCE_SIZE);

    // Anti-replay sliding window (matches Rust crypto.rs)
    const recvNonce = new DataView(nonce.buffer, nonce.byteOffset, 8).getBigUint64(0, true);
    const windowSize = BigInt(WINDOW_SIZE);

    if (recvNonce > this.recvWindow) {
      const diff = recvNonce - this.recvWindow;
      this.recvBitmap = diff >= windowSize
        ? BigInt(1)
        : (this.recvBitmap << diff) | BigInt(1);
      this.recvWindow = recvNonce;
    } else if (recvNonce === this.recvWindow) {
      throw new DecryptError("nonce reuse detected");
    } else {
      const offset = this.recvWindow - recvNonce;
      if (offset > windowSize) throw new DecryptError("nonce reuse detected");
      const mask = BigInt(1) << (offset - BigInt(1));
      if (this.recvBitmap & mask) throw new DecryptError("nonce reuse detected");
      this.recvBitmap |= mask;
    }

    try {
      const plaintext = await crypto.subtle.decrypt(
        { name: AEAD_ALGORITHM, nonce, additionalData: new Uint8Array(0) } as any,
        this.recvKey, asBufferSource(ciphertext)
      );
      return new Uint8Array(plaintext);
    } catch {
      throw new DecryptError("authentication failed");
    }
  }

  async buildEncryptedFrame(
    frameType: number, flags: number, plaintext: Uint8Array
  ): Promise<Uint8Array> {
    const encryptedPayload = await this.encrypt(plaintext);
    const total = buildSize(encryptedPayload.length);
    const buf = new Uint8Array(total);
    buildFrame(frameType, flags | FLAG_ENCRYPTED, encryptedPayload, buf, 0);
    return buf;
  }
}

// ═══ Errors ═════════════════════════════════════════════════════════════════

export class DecryptError extends Error {
  constructor(message: string) {
    super(`LUMEN DecryptError: ${message}`);
    this.name = "DecryptError";
  }
}

// ═══ Helpers ════════════════════════════════════════════════════════════════

export function encryptedLen(plaintextLen: number): number {
  return NONCE_SIZE + plaintextLen + TAG_SIZE;
}
