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
 * The TAG is appended automatically by the AEAD cipher.
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
 * 4. Cipher initialized with shared secret as ChaCha20-Poly1305 key
 */

import {
  buildFrame,
  buildSize,
  FLAG_ENCRYPTED,
} from "./frame.js";

// ═══ Constants ══════════════════════════════════════════════════════════════

/** ChaCha20-Poly1305 nonce size in bytes. */
export const NONCE_SIZE = 12;

/** Poly1305 authentication tag size in bytes (appended to ciphertext). */
export const TAG_SIZE = 16;

/** X25519 public key size in bytes. */
export const PUBLIC_KEY_SIZE = 32;

/** X25519 secret key size in bytes. */
export const SECRET_KEY_SIZE = 32;

/** Total overhead per encrypted frame: nonce (12B) + tag (16B) = 28 bytes. */
export const ENCRYPTION_OVERHEAD = NONCE_SIZE + TAG_SIZE;

/** AEAD algorithm identifier for Web Crypto. */
const AEAD_ALGORITHM = "ChaCha20-Poly1305";

/** Key derivation: raw X25519 shared secret is used directly. */
const KEY_ALGORITHM = "ChaCha20-Poly1305";

// ═══ Keypair ════════════════════════════════════════════════════════════════

/**
 * An X25519 keypair for LUMEN wire encryption.
 */
export interface Keypair {
  secretKey: Uint8Array; // 32 bytes
  publicKey: Uint8Array; // 32 bytes
}

/**
 * Generate a new random X25519 keypair using Web Crypto.
 */
export async function generateKeypair(): Promise<Keypair> {
  const kp = await crypto.subtle.generateKey(
    "X25519",
    true, // extractable
    ["deriveBits"]
  ) as CryptoKeyPair;

  const publicKey = new Uint8Array(
    await crypto.subtle.exportKey("raw", kp.publicKey)
  );
  const secretKey = new Uint8Array(
    await crypto.subtle.exportKey("raw", kp.privateKey)
  );

  return { secretKey, publicKey };
}

/**
 * Derive a 256-bit shared secret from our secret key and peer's public key.
 */
export async function deriveSharedSecret(
  secretKey: Uint8Array,
  peerPublicKey: Uint8Array
): Promise<Uint8Array> {
  const ourKey = await crypto.subtle.importKey(
    "raw",
    secretKey,
    "X25519",
    false,
    ["deriveBits"]
  );

  const peerKey = await crypto.subtle.importKey(
    "raw",
    peerPublicKey,
    "X25519",
    false,
    []
  );

  const sharedBits = await crypto.subtle.deriveBits(
    {
      name: "X25519",
      public: peerKey,
    },
    ourKey,
    256
  );

  return new Uint8Array(sharedBits);
}

// ═══ Cipher ═════════════════════════════════════════════════════════════════

/**
 * An initialized LUMEN cipher with a derived shared key.
 *
 * Maintains independent nonce counters for each direction.
 */
export class Cipher {
  private key: CryptoKey;
  private sendCounter: bigint = 0n;
  private recvCounter: bigint = 0n;
  private _initialized = false;

  /**
   * Create a new cipher. Call `await cipher.init(sharedSecret)` before use.
   */
  constructor() {}

  /**
   * Initialize the cipher with a 32-byte shared secret.
   */
  async init(sharedSecret: Uint8Array): Promise<void> {
    this.key = await crypto.subtle.importKey(
      "raw",
      sharedSecret,
      { name: AEAD_ALGORITHM },
      false,
      ["encrypt", "decrypt"]
    );
    this.sendCounter = 0n;
    this.recvCounter = 0n;
    this._initialized = true;
  }

  get initialized(): boolean {
    return this._initialized;
  }

  /**
   * Build a 12-byte nonce from a counter value (little-endian u64 + 4 zero bytes).
   */
  private static makeNonce(counter: bigint): Uint8Array {
    const nonce = new Uint8Array(NONCE_SIZE);
    const view = new DataView(nonce.buffer);
    view.setBigUint64(0, counter, true); // little-endian
    // bytes 8-11 remain zero
    return nonce;
  }

  /**
   * Encrypt a plaintext frame payload.
   *
   * Returns `[NONCE:12B][CIPHERTEXT+tag]`.
   */
  async encrypt(plaintext: Uint8Array): Promise<Uint8Array> {
    if (!this._initialized) throw new Error("Cipher not initialized");

    const nonce = Cipher.makeNonce(this.sendCounter);
    this.sendCounter += 1n;

    const ciphertext = new Uint8Array(
      await crypto.subtle.encrypt(
        { name: AEAD_ALGORITHM, nonce, additionalData: new Uint8Array(0) },
        this.key,
        plaintext
      )
    );

    const out = new Uint8Array(NONCE_SIZE + ciphertext.length);
    out.set(nonce, 0);
    out.set(ciphertext, NONCE_SIZE);
    return out;
  }

  /**
   * Decrypt a received encrypted payload.
   *
   * Expects `[NONCE:12B][CIPHERTEXT+tag]`. Returns the plaintext.
   */
  async decrypt(encrypted: Uint8Array): Promise<Uint8Array> {
    if (!this._initialized) throw new Error("Cipher not initialized");

    if (encrypted.length < NONCE_SIZE + TAG_SIZE) {
      throw new DecryptError("encrypted payload too short");
    }

    const nonce = encrypted.slice(0, NONCE_SIZE);
    const ciphertext = encrypted.slice(NONCE_SIZE);

    // Nonce replay detection
    const view = new DataView(nonce.buffer, nonce.byteOffset, 8);
    const recvNonce = view.getBigUint64(0, true);
    if (recvNonce < this.recvCounter) {
      throw new DecryptError("nonce reuse detected");
    }
    this.recvCounter = recvNonce + 1n;

    try {
      const plaintext = await crypto.subtle.decrypt(
        { name: AEAD_ALGORITHM, nonce, additionalData: new Uint8Array(0) },
        this.key,
        ciphertext
      );
      return new Uint8Array(plaintext);
    } catch {
      throw new DecryptError("authentication failed");
    }
  }

  /**
   * Encrypt and build a full LUMEN frame (with Hyb128 + TYPE + FLAGS).
   *
   * Returns the complete frame bytes ready for transport.
   */
  async buildEncryptedFrame(
    frameType: number,
    flags: number,
    plaintext: Uint8Array
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

/**
 * Calculate the total encrypted payload size for a given plaintext length.
 */
export function encryptedLen(plaintextLen: number): number {
  return NONCE_SIZE + plaintextLen + TAG_SIZE;
}
