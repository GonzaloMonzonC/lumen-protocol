<?php
/**
 * Hyb128 — Hybrid length encoding with O(1) decode.
 *
 * Encoding scheme:
 *   Mode 00: 1 byte  (0–63)
 *   Mode 10: 3 bytes (64–65535, u16 LE)
 *   Mode 11: 5 bytes (65536–4294967295, u32 LE)
 *   Mode 01: 2–11 bytes (LEB128 fallback)
 *
 * Ported from Python src/lumen/hyb128.py.
 */

namespace Lumen;

final class Hyb128
{
    public const MAX_SHORT = 0x3F;
    public const MAX_ENCODED_LEN = 11;

    private const MODE_MASK = 0xC0;
    private const SHORT_MASK = 0x3F;
    private const MODE_SHORT = 0x00;
    private const MODE_LEB128 = 0x40;
    private const MODE_U16 = 0x80;
    private const MODE_U32 = 0xC0;

    // ── Encode ──────────────────────────────────────────────────────────

    /**
     * Encode $value into $buf at $offset. Returns bytes written.
     *
     * @throws \InvalidArgumentException if value is negative
     */
    public static function encode(int $value, string &$buf, int $offset = 0): int
    {
        if ($value < 0) {
            throw new \InvalidArgumentException("Hyb128.encode: value must be non-negative, got $value");
        }

        if ($value <= self::MAX_SHORT) {
            $buf[$offset] = chr(self::MODE_SHORT | $value);
            return 1;
        }

        if ($value <= 0xFFFF) {
            $buf[$offset] = chr(self::MODE_U16);
            $buf[$offset + 1] = chr($value & 0xFF);
            $buf[$offset + 2] = chr(($value >> 8) & 0xFF);
            return 3;
        }

        if ($value <= 0xFFFFFFFF) {
            $buf[$offset] = chr(self::MODE_U32);
            $buf[$offset + 1] = chr($value & 0xFF);
            $buf[$offset + 2] = chr(($value >> 8) & 0xFF);
            $buf[$offset + 3] = chr(($value >> 16) & 0xFF);
            $buf[$offset + 4] = chr(($value >> 24) & 0xFF);
            return 5;
        }

        // LEB128 fallback
        $buf[$offset] = chr(self::MODE_LEB128);
        return 1 + self::leb128Encode($value, $buf, $offset + 1);
    }

    /** One-shot encode returning raw bytes. */
    public static function encodeBytes(int $value): string
    {
        if ($value <= self::MAX_SHORT) {
            return chr(self::MODE_SHORT | $value);
        }
        $buf = str_repeat("\0", self::MAX_ENCODED_LEN);
        $n = self::encode($value, $buf, 0);
        return substr($buf, 0, $n);
    }

    /** Bytes needed to encode $value in Hyb128. */
    public static function encodedLen(int $value): int
    {
        if ($value <= self::MAX_SHORT) return 1;
        if ($value <= 0xFFFF) return 3;
        if ($value <= 0xFFFFFFFF) return 5;
        return 1 + self::leb128Len($value);
    }

    // ── Decode ──────────────────────────────────────────────────────────

    /**
     * Decode Hyb128 from $data at $offset.
     * Returns ['value' => int, 'headerLen' => int] or null.
     */
    public static function decode(string $data, int $offset = 0): ?array
    {
        if ($offset >= strlen($data)) return null;

        $first = ord($data[$offset]);
        $mode = $first & self::MODE_MASK;

        if ($mode === self::MODE_SHORT) {
            return ['value' => $first & self::SHORT_MASK, 'headerLen' => 1];
        }

        if ($mode === self::MODE_U16) {
            if ($offset + 3 > strlen($data)) return null;
            $value = ord($data[$offset + 1]) | (ord($data[$offset + 2]) << 8);
            return ['value' => $value, 'headerLen' => 3];
        }

        if ($mode === self::MODE_U32) {
            if ($offset + 5 > strlen($data)) return null;
            $value = ord($data[$offset + 1])
                   | (ord($data[$offset + 2]) << 8)
                   | (ord($data[$offset + 3]) << 16)
                   | (ord($data[$offset + 4]) << 24);
            return ['value' => $value, 'headerLen' => 5];
        }

        // LEB128 fallback
        return self::leb128Decode($data, $offset + 1);
    }

    // ── LEB128 helpers ──────────────────────────────────────────────────

    public static function leb128Len(int $value): int
    {
        if ($value === 0) return 1;
        $len = 0;
        while ($value > 0) { $len++; $value >>= 7; }
        return $len;
    }

    public static function leb128Encode(int $value, string &$buf, int $offset): int
    {
        $written = 0;
        do {
            $byte = $value & 0x7F;
            $value >>= 7;
            if ($value !== 0) $byte |= 0x80;
            $buf[$offset + $written] = chr($byte);
            $written++;
        } while ($value > 0);
        return $written;
    }

    /**
     * Decode LEB128 from $data at $offset (mode byte already consumed).
     * Returns ['value' => int, 'headerLen' => int] or null.
     * headerLen includes the mode byte.
     */
    public static function leb128Decode(string $data, int $offset): ?array
    {
        $value = 0;
        $shift = 0;
        $len = strlen($data);
        for ($i = 0; $i < 10; $i++) {
            if ($offset + $i >= $len) return null;
            $byte = ord($data[$offset + $i]);
            $value |= ($byte & 0x7F) << $shift;
            if (($byte & 0x80) === 0) {
                return ['value' => $value, 'headerLen' => 1 + $i + 1]; // +1 for mode byte
            }
            $shift += 7;
        }
        return null;
    }
}
