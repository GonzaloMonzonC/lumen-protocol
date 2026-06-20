<?php
/**
 * Compact binary payload compression/decompression.
 *
 * Value tags:
 *   TAG_NULL     = 0xE0
 *   TAG_BOOL     = 0xE1 <0|1:1B>
 *   TAG_FLOAT    = 0xE2 <f64 LE:8B>
 *   TAG_INT      = 0xE3 <zigzag LEB128>
 *   TAG_STR_DICT = 0xE4 <id:1B>
 *   TAG_STR_RAW  = 0xE5 <len:Hyb128> <utf8>
 *   TAG_ARRAY    = 0xE6 <count:Hyb128> value*
 *   TAG_OBJECT   = 0xE7 <count:Hyb128> (key value)*
 *
 * Keys inside objects:
 *   0x00-0xFE = dict ID
 *   0xFF      = raw UTF-8
 */

namespace Lumen;

final class Compress
{
    private const TAG_NULL     = 0xE0;
    private const TAG_BOOL     = 0xE1;
    private const TAG_FLOAT    = 0xE2;
    private const TAG_INT      = 0xE3;
    private const TAG_STR_DICT = 0xE4;
    private const TAG_STR_RAW  = 0xE5;
    private const TAG_ARRAY    = 0xE6;
    private const TAG_OBJECT   = 0xE7;

    private const MAX_COUNT = 1024;

    /** Maximum nesting depth for containers (arrays and objects). 32 = Python/Rust parity. */
    private const MAX_DEPTH = 32;

    // ── Public API ──────────────────────────────────────────────────────

    /**
     * Compress a JSON-compatible value into LUMEN compact binary.
     */
    public static function compress(mixed $value): string
    {
        $chunks = [];
        self::encodeValue($value, $chunks);
        return implode('', $chunks);
    }

    /**
     * Decompress LUMEN compact binary back into a JSON-compatible value.
     * Returns null if input is malformed.
     */
    public static function decompress(string $data): mixed
    {
        if ($data === '') return null;
        $result = self::decodeValue($data, 0, strlen($data));
        return $result[0];
    }

    // ── Encoder ─────────────────────────────────────────────────────────

    /** @param list<string> $out */
    private static function encodeValue(mixed $value, array &$out): void
    {
        if ($value === null) {
            $out[] = chr(self::TAG_NULL);
            return;
        }

        if (is_bool($value)) {
            $out[] = chr(self::TAG_BOOL) . chr($value ? 1 : 0);
            return;
        }

        if (is_int($value)) {
            $out[] = chr(self::TAG_INT) . self::encodeZigzag($value);
            return;
        }

        if (is_float($value)) {
            $buf = chr(self::TAG_FLOAT);
            $buf .= pack('e', $value); // f64 little-endian
            $out[] = $buf;
            return;
        }

        if (is_string($value)) {
            $dictId = Dict::lookup($value);
            if ($dictId !== null) {
                $out[] = chr(self::TAG_STR_DICT) . chr($dictId);
                return;
            }
            $utf8 = $value; // PHP strings are already byte strings
            $lenBuf = Hyb128::encodeBytes(strlen($utf8));
            $out[] = chr(self::TAG_STR_RAW) . $lenBuf . $utf8;
            return;
        }

        if (is_array($value) && array_is_list($value)) {
            $countBuf = Hyb128::encodeBytes(count($value));
            $out[] = chr(self::TAG_ARRAY) . $countBuf;
            foreach ($value as $v) {
                self::encodeValue($v, $out);
            }
            return;
        }

        if (is_array($value)) {
            $keys = array_keys($value);
            $countBuf = Hyb128::encodeBytes(count($keys));
            $out[] = chr(self::TAG_OBJECT) . $countBuf;
            foreach ($value as $k => $v) {
                self::encodeKey((string) $k, $out);
                self::encodeValue($v, $out);
            }
            return;
        }

        if ($value instanceof EmptyObject) {
            $out[] = chr(self::TAG_OBJECT) . chr(0); // count=0
            return;
        }

        // Unsupported type → null
        $out[] = chr(self::TAG_NULL);
    }

    /** @param list<string> $out */
    private static function encodeKey(string $key, array &$out): void
    {
        $dictId = Dict::lookup($key);
        if ($dictId !== null) {
            $out[] = chr($dictId);
            return;
        }
        $lenBuf = Hyb128::encodeBytes(strlen($key));
        $out[] = chr(Dict::ID_RAW) . $lenBuf . $key;
    }

    // ── Decoder ─────────────────────────────────────────────────────────

    /** @return array{mixed, int} [value, newPos] */
    private static function decodeValue(string $data, int $pos, int $end, int $depth = 0): array
    {
        if ($depth > self::MAX_DEPTH) return [null, $pos]; // reject deeply nested payloads
        if ($pos >= $end) return [null, $pos];

        $tag = ord($data[$pos]);
        $pos++;

        switch ($tag) {
            case self::TAG_NULL:
                return [null, $pos];

            case self::TAG_BOOL:
                if ($pos >= $end) return [null, $pos];
                return [ord($data[$pos]) !== 0, $pos + 1];

            case self::TAG_FLOAT:
                if ($pos + 8 > $end) return [null, $pos];
                $value = unpack('e', substr($data, $pos, 8))[1];
                return [$value, $pos + 8];

            case self::TAG_INT:
                return self::decodeZigzag($data, $pos, $end);

            case self::TAG_STR_DICT:
                if ($pos >= $end) return [null, $pos];
                return [Dict::resolve(ord($data[$pos])), $pos + 1];

            case self::TAG_STR_RAW:
                $decoded = Hyb128::decode($data, $pos);
                if ($decoded === null) return [null, $pos];
                $len = $decoded['value'];
                $pos += $decoded['headerLen'];
                if ($pos + $len > $end) return [null, $pos];
                $s = substr($data, $pos, $len);
                return [$s, $pos + $len];

            case self::TAG_ARRAY:
                $decoded = Hyb128::decode($data, $pos);
                if ($decoded === null) return [null, $pos];
                $count = min($decoded['value'], self::MAX_COUNT);
                $pos += $decoded['headerLen'];
                $arr = [];
                for ($i = 0; $i < $count; $i++) {
                    [$val, $pos] = self::decodeValue($data, $pos, $end, $depth + 1);
                    $arr[] = $val;
                }
                return [$arr, $pos];

            case self::TAG_OBJECT:
                $decoded = Hyb128::decode($data, $pos);
                if ($decoded === null) return [null, $pos];
                $count = min($decoded['value'], self::MAX_COUNT);
                $pos += $decoded['headerLen'];
                $obj = [];
                for ($i = 0; $i < $count; $i++) {
                    [$key, $pos] = self::decodeKey($data, $pos, $end);
                    [$val, $pos] = self::decodeValue($data, $pos, $end, $depth + 1);
                    $obj[$key] = $val;
                }
                return [$obj, $pos];

            default:
                return [null, $pos];
        }
    }

    /** @return array{string, int} [key, newPos] */
    private static function decodeKey(string $data, int $pos, int $end): array
    {
        if ($pos >= $end) return ['', $pos];
        $id = ord($data[$pos]);
        if ($id === Dict::ID_RAW) {
            $pos++;
            $decoded = Hyb128::decode($data, $pos);
            if ($decoded === null) return ['', $pos];
            $len = $decoded['value'];
            $pos += $decoded['headerLen'];
            if ($pos + $len > $end) return ['', $pos];
            $key = substr($data, $pos, $len);
            return [$key, $pos + $len];
        }
        return [Dict::resolve($id) ?? '', $pos + 1];
    }

    // ── Zigzag LEB128 ───────────────────────────────────────────────────

    /** Encode signed int as zigzag LEB128 bytes. */
    private static function encodeZigzag(int $v): string
    {
        // Zigzag: (n << 1) ^ (n >> 63). PHP 64-bit bitwise ops are naturally
        // clamped to 64 bits, no mask needed.
        $u = ($v << 1) ^ ($v >> 63);
        $buf = '';
        do {
            $byte = $u & 0x7F;
            $u >>= 7;
            if ($u !== 0) $byte |= 0x80;
            $buf .= chr($byte);
        } while ($u !== 0);
        return $buf;
    }

    /** Decode zigzag LEB128 from data. @return array{int, int} [value, newPos] */
    private static function decodeZigzag(string $data, int $pos, int $end): array
    {
        $u = 0;
        $shift = 0;
        for ($i = 0; $i < 10; $i++) {
            if ($pos >= $end) return [0, $pos];
            $byte = ord($data[$pos]);
            $pos++;
            $u |= ($byte & 0x7F) << $shift;
            if (($byte & 0x80) === 0) {
                // Zigzag decode: (u >> 1) ^ -(u & 1)
                return [($u >> 1) ^ -($u & 1), $pos];
            }
            $shift += 7;
        }
        return [0, $pos];
    }
}
