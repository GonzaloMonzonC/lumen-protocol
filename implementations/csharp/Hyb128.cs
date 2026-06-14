/// <summary>
/// Hyb128 codec — hybrid 1/3/5-byte variable-length encoding.
/// Mirrors implementations/rust/src/hyb128.rs exactly.
/// </summary>
namespace Lumen;

public static class Hyb128
{
    /// <summary>Maximum encoded length for a Hyb128 value.</summary>
    public const int MAX_ENCODED_LEN = 11;

    /// <summary>Encode a value into a span. Returns bytes written.</summary>
    public static int Encode(ulong value, Span<byte> dest)
    {
        if (value <= 63)
        {
            dest[0] = (byte)value;
            return 1;
        }

        if (value <= 65535)
        {
            dest[0] = 0x80;
            WriteU16LE(dest[1..], (ushort)value);
            return 3;
        }

        if (value <= 4294967295)
        {
            dest[0] = 0xC0;
            WriteU32LE(dest[1..], (uint)value);
            return 5;
        }

        // LEB128 fallback for >4 GiB
        dest[0] = 0x40;
        int pos = 1;
        ulong v = value;
        while (v > 0)
        {
            byte b = (byte)(v & 0x7F);
            v >>= 7;
            if (v > 0) b |= 0x80;
            dest[pos++] = b;
        }
        return pos;
    }

    /// <summary>Decode a Hyb128 value from a span. Returns (value, bytesRead) or null.</summary>
    public static (ulong value, int bytesRead)? Decode(ReadOnlySpan<byte> source)
    {
        if (source.Length == 0) return null;

        byte first = source[0];
        int mode = first & 0xC0;

        return mode switch
        {
            0x00 => ((ulong)(first & 0x3F), 1),
            0x80 => source.Length >= 3 ? (ReadU16LE(source[1..]), 3) : null,
            0xC0 => source.Length >= 5 ? (ReadU32LE(source[1..]), 5) : null,
            0x40 => DecodeLeb128(source[1..]),
            _ => null,
        };
    }

    /// <summary>Measure encoded length of a value without encoding.</summary>
    public static int EncodedLen(ulong value) => value switch
    {
        <= 63 => 1,
        <= 65535 => 3,
        <= 4294967295 => 5,
        _ => Leb128Len(value),
    };

    // ── LEB128 helpers ──

    private static (ulong value, int bytesRead)? DecodeLeb128(ReadOnlySpan<byte> source)
    {
        ulong result = 0;
        int shift = 0;
        for (int i = 0; i < source.Length; i++)
        {
            byte b = source[i];
            result |= (ulong)(b & 0x7F) << shift;
            if ((b & 0x80) == 0)
                return (result, 1 + i + 1); // mode byte + continuation bytes
            shift += 7;
            if (shift >= 64) return null;
        }
        return null;
    }

    private static int Leb128Len(ulong v)
    {
        int len = 1; // mode byte
        while (v > 0) { len++; v >>= 7; }
        return len;
    }

    private static ushort ReadU16LE(ReadOnlySpan<byte> s) =>
        (ushort)(s[0] | (s[1] << 8));

    private static uint ReadU32LE(ReadOnlySpan<byte> s) =>
        (uint)(s[0] | (s[1] << 8) | (s[2] << 16) | (s[3] << 24));

    private static void WriteU16LE(Span<byte> s, ushort v)
    {
        s[0] = (byte)v;
        s[1] = (byte)(v >> 8);
    }

    private static void WriteU32LE(Span<byte> s, uint v)
    {
        s[0] = (byte)v;
        s[1] = (byte)(v >> 8);
        s[2] = (byte)(v >> 16);
        s[3] = (byte)(v >> 24);
    }
}
