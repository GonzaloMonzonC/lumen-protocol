/**
 * PDB Edge — Subkey encoding/decoding
 * 
 * MUMPS-style hierarchical subscripts encoded as:
 *   \x02 + string + \xff  per subscript level
 * 
 * Ported from pdb_tools.py (Python) to TypeScript
 */

// ── Encoding ──

export function encodeSubs(subs: (string | number)[]): Uint8Array {
  const parts: Uint8Array[] = []
  for (const s of subs) {
    const str = String(s)
    const encoded = new Uint8Array(2 + str.length)
    encoded[0] = 0x02
    for (let i = 0; i < str.length; i++) {
      encoded[1 + i] = str.charCodeAt(i)
    }
    encoded[encoded.length - 1] = 0xff
    parts.push(encoded)
  }
  // Concatenate all parts
  const totalLen = parts.reduce((acc, p) => acc + p.length, 0)
  const result = new Uint8Array(totalLen)
  let offset = 0
  for (const p of parts) {
    result.set(p, offset)
    offset += p.length
  }
  return result
}

/**
 * Encode a prefix subkey (for $ORDER and prefix matching).
 * Same as encodeSubs but the last level is encoded WITHOUT the trailing \xff
 * so that subkeys that START with this prefix will match.
 */
export function encodePrefix(subs: (string | number)[]): Uint8Array {
  if (subs.length === 0) return new Uint8Array(0)
  const prefix_subs = subs.slice(0, -1)
  const last = String(subs[subs.length - 1])
  const prefix = encodeSubs(prefix_subs)
  const lastEncoded = new Uint8Array(1 + last.length) // no trailing \xff
  lastEncoded[0] = 0x02
  for (let i = 0; i < last.length; i++) {
    lastEncoded[1 + i] = last.charCodeAt(i)
  }
  const result = new Uint8Array(prefix.length + lastEncoded.length)
  result.set(prefix, 0)
  result.set(lastEncoded, prefix.length)
  return result
}

// ── Decoding ──

export function decodeSubs(data: Uint8Array): (string | number)[] {
  const subs: (string | number)[] = []
  let i = 0
  while (i < data.length) {
    if (data[i] !== 0x02) {
      // Legacy or corrupted — skip to next 0x02
      i++
      continue
    }
    i++ // skip 0x02
    const start = i
    while (i < data.length && data[i] !== 0xff) {
      i++
    }
    const str = new TextDecoder().decode(data.slice(start, i))
    if (i < data.length) i++ // skip 0xff
    // Try to parse as number for numeric subscripts
    const num = Number(str)
    subs.push(Number.isInteger(num) && str !== '' ? num : str)
  }
  return subs
}

export function decodeLastSub(data: Uint8Array): string | number | null {
  const subs = decodeSubs(data)
  return subs.length > 0 ? subs[subs.length - 1] : null
}

// ── Utility ──

export function incrementBytes(buf: Uint8Array): Uint8Array {
  // Return the smallest byte array that is strictly greater than buf
  const result = new Uint8Array(buf.length)
  result.set(buf)
  for (let i = result.length - 1; i >= 0; i--) {
    if (result[i] < 0xff) {
      result[i]++
      return result
    }
    result[i] = 0x00
  }
  // Overflow: prepend 0x01
  const overflow = new Uint8Array(buf.length + 1)
  overflow[0] = 0x01
  return overflow
}

export function subkeyToString(buf: Uint8Array): string {
  const subs = decodeSubs(buf)
  return subs.map(s => String(s)).join(',')
}
