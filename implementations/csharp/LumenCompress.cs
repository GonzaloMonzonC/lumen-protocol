using System.Buffers;
using System.Text;
using System.Text.Json;

namespace Lumen;

/// <summary>
/// Compact binary payload compression — C# port of Rust <c>compress.rs</c>.
/// </summary>
public static class LumenCompress
{
    // ═══ Value tags ════════════════════════════════════════════════════════

    private const byte TAG_NULL = 0xE0;
    private const byte TAG_BOOL = 0xE1;
    private const byte TAG_FLOAT = 0xE2;
    private const byte TAG_INT = 0xE3;
    private const byte TAG_STR_DICT = 0xE4;
    private const byte TAG_STR_RAW = 0xE5;
    private const byte TAG_ARRAY = 0xE6;
    private const byte TAG_OBJECT = 0xE7;

    private const int MAX_COUNT = 1024;

    private static readonly UTF8Encoding Utf8 = new(false, true);

    // ═══ Public API ═════════════════════════════════════════════════════════

    /// <summary>Compress a JSON element into LUMEN compact binary.</summary>
    public static byte[] CompressValue(JsonElement value)
    {
        using var buffer = new ArrayPoolBuffer();
        EncodeValue(value, buffer);
        return buffer.ToArray();
    }

    /// <summary>Decompress LUMEN binary → JSON element. Returns null on malformed input.</summary>
    public static JsonElement? DecompressValue(ReadOnlySpan<byte> data)
    {
        if (data.Length == 0) return null;
        int pos = 0;
        var result = DecodeValue(data, ref pos, data.Length);
        if (result is null) return null;
        // Recursively replace null sentinels with actual null for JSON serialization
        NormalizeNull(ref result);
        return JsonSerializer.SerializeToElement(result);
    }

    /// <summary>Recursively replace NullSentinelType with actual null in decoded trees.</summary>
    private static void NormalizeNull(ref object? value)
    {
        if (ReferenceEquals(value, NullSentinelType.Value))
        {
            value = null;
        }
        else if (value is object?[] arr)
        {
            for (int i = 0; i < arr.Length; i++)
            {
                var elem = arr[i];
                NormalizeNull(ref elem);
                arr[i] = elem;
            }
        }
        else if (value is Dictionary<string, object?> obj)
        {
            var keys = obj.Keys.ToArray();
            foreach (var key in keys)
            {
                var val = obj[key];
                NormalizeNull(ref val);
                obj[key] = val;
            }
        }
    }

    /// <summary>Sentinel for JSON null — distinguishes TAG_NULL from decode errors.</summary>
    private sealed class NullSentinelType { internal static readonly NullSentinelType Value = new(); }

    /// <summary>Estimate compressed size (for buffer pre-allocation).</summary>
    public static int CompressedSize(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.Null or JsonValueKind.Undefined => 1,
        JsonValueKind.True or JsonValueKind.False => 2,
        JsonValueKind.Number => EstimateNumberSize(value),
        JsonValueKind.String => EstimateStringSize(value.GetString()!),
        JsonValueKind.Array => EstimateArraySize(value),
        JsonValueKind.Object => EstimateObjectSize(value),
        _ => 1,
    };

    // ═══ Encoder ═══════════════════════════════════════════════════════════

    private static void EncodeValue(JsonElement value, ArrayPoolBuffer out_)
    {
        switch (value.ValueKind)
        {
            case JsonValueKind.Null:
            case JsonValueKind.Undefined:
                out_.WriteByte(TAG_NULL);
                break;

            case JsonValueKind.True:
                out_.WriteBytes([TAG_BOOL, 1]);
                break;

            case JsonValueKind.False:
                out_.WriteBytes([TAG_BOOL, 0]);
                break;

            case JsonValueKind.Number:
                if (value.TryGetInt64(out var i64))
                {
                    out_.WriteByte(TAG_INT);
                    EncodeI64Leb128(i64, out_);
                }
                else
                {
                    // Float
                    Span<byte> buf = stackalloc byte[9];
                    buf[0] = TAG_FLOAT;
                    BitConverter.TryWriteBytes(buf[1..], value.GetDouble());
                    out_.WriteBytes(buf);
                }
                break;

            case JsonValueKind.String:
            {
                var s = value.GetString()!;
                var dictId = Dict.LookupId(s);
                if (dictId.HasValue)
                {
                    out_.WriteBytes([TAG_STR_DICT, dictId.Value]);
                }
                else
                {
                    var utf8 = Utf8.GetBytes(s);
                    out_.WriteByte(TAG_STR_RAW);
                    EncodeHyb128((ulong)utf8.Length, out_);
                    out_.WriteBytes(utf8);
                }
                break;
            }

            case JsonValueKind.Array:
            {
                var count = value.GetArrayLength();
                out_.WriteByte(TAG_ARRAY);
                EncodeHyb128((ulong)count, out_);
                foreach (var item in value.EnumerateArray())
                {
                    if (--count < 0) break; // safety cap
                    EncodeValue(item, out_);
                }
                break;
            }

            case JsonValueKind.Object:
            {
                int count = 0;
                foreach (var _ in value.EnumerateObject()) count++;
                out_.WriteByte(TAG_OBJECT);
                EncodeHyb128((ulong)count, out_);
                int cap = MAX_COUNT;
                foreach (var prop in value.EnumerateObject())
                {
                    if (cap-- <= 0) break;
                    EncodeKey(prop.Name, out_);
                    EncodeValue(prop.Value, out_);
                }
                break;
            }
        }
    }

    private static void EncodeKey(string key, ArrayPoolBuffer out_)
    {
        var dictId = Dict.LookupId(key);
        if (dictId.HasValue)
        {
            out_.WriteByte(dictId.Value);
        }
        else
        {
            out_.WriteByte(Dict.ID_RAW);
            var utf8 = Utf8.GetBytes(key);
            EncodeHyb128((ulong)utf8.Length, out_);
            out_.WriteBytes(utf8);
        }
    }

    // ═══ Decoder ═══════════════════════════════════════════════════════════

    private static object? DecodeValue(ReadOnlySpan<byte> data, ref int pos, int end)
    {
        if (pos >= end) return null;

        byte tag = data[pos++];

        return tag switch
        {
            TAG_NULL => NullSentinelType.Value,
            TAG_BOOL => pos < end ? (data[pos++] != 0) : (object?)null,
            TAG_FLOAT => DecodeFloat(data, ref pos, end),
            TAG_INT => DecodeI64Leb128(data, ref pos, end),
            TAG_STR_DICT => DecodeStrDict(data, ref pos, end),
            TAG_STR_RAW => DecodeStrRaw(data, ref pos, end),
            TAG_ARRAY => DecodeArray(data, ref pos, end),
            TAG_OBJECT => DecodeObject(data, ref pos, end),
            _ => null,
        };
    }

    private static double? DecodeFloat(ReadOnlySpan<byte> data, ref int pos, int end)
    {
        if (pos + 8 > end) return null;
        double v = BitConverter.ToDouble(data[pos..(pos + 8)]);
        pos += 8;
        return v;
    }

    private static string? DecodeStrDict(ReadOnlySpan<byte> data, ref int pos, int end)
    {
        if (pos >= end) return null;
        return Dict.ResolveId(data[pos++]);
    }

    private static string? DecodeStrRaw(ReadOnlySpan<byte> data, ref int pos, int end)
    {
        var decoded = Hyb128.Decode(data[pos..]);
        if (decoded is null) return null;
        pos += decoded.Value.bytesRead;
        var len = (int)decoded.Value.value;
        if (pos + len > end) return null;
        try
        {
            var s = Utf8.GetString(data[pos..(pos + len)]);
            pos += len;
            return s;
        }
        catch { return null; }
    }

    private static object[]? DecodeArray(ReadOnlySpan<byte> data, ref int pos, int end)
    {
        var decoded = Hyb128.Decode(data[pos..]);
        if (decoded is null) return null;
        pos += decoded.Value.bytesRead;
        var count = Math.Min((int)decoded.Value.value, MAX_COUNT);
        var arr = new object?[count];
        for (int i = 0; i < count; i++)
        {
            arr[i] = DecodeValue(data, ref pos, end);
        }
        return arr!;
    }

    private static Dictionary<string, object?>? DecodeObject(ReadOnlySpan<byte> data, ref int pos, int end)
    {
        var decoded = Hyb128.Decode(data[pos..]);
        if (decoded is null) return null;
        pos += decoded.Value.bytesRead;
        var count = Math.Min((int)decoded.Value.value, MAX_COUNT);
        var obj = new Dictionary<string, object?>(count);
        for (int i = 0; i < count; i++)
        {
            var key = DecodeKey(data, ref pos, end);
            var val = DecodeValue(data, ref pos, end);
            if (key is not null)
                obj[key] = val;
        }
        return obj;
    }

    private static string? DecodeKey(ReadOnlySpan<byte> data, ref int pos, int end)
    {
        if (pos >= end) return null;
        byte first = data[pos++];

        if (first == Dict.ID_RAW)
        {
            var decoded = Hyb128.Decode(data[pos..]);
            if (decoded is null) return null;
            pos += decoded.Value.bytesRead;
            var len = (int)decoded.Value.value;
            if (pos + len > end) return null;
            try
            {
                var s = Utf8.GetString(data[pos..(pos + len)]);
                pos += len;
                return s;
            }
            catch { return null; }
        }
        else if (first < Dict.STATIC_MAX)
        {
            return Dict.ResolveId(first);
        }
        else
        {
            return null; // session-range IDs not yet supported
        }
    }

    // ═══ Hyb128 inline helpers ════════════════════════════════════════════

    private static void EncodeHyb128(ulong value, ArrayPoolBuffer out_)
    {
        Span<byte> buf = stackalloc byte[Hyb128.MAX_ENCODED_LEN];
        int len = Hyb128.Encode(value, buf);
        out_.WriteBytes(buf[..len]);
    }

    // ═══ Zigzag LEB128 for i64 ═════════════════════════════════════════════

    private static void EncodeI64Leb128(long v, ArrayPoolBuffer out_)
    {
        ulong u = ((ulong)v << 1) ^ (ulong)(v >> 63);
        while (u > 0x7F)
        {
            out_.WriteByte((byte)((u & 0x7F) | 0x80));
            u >>= 7;
        }
        out_.WriteByte((byte)u);
    }

    private static long? DecodeI64Leb128(ReadOnlySpan<byte> data, ref int pos, int end)
    {
        ulong u = 0;
        int shift = 0;
        for (int i = 0; i < 10; i++)
        {
            if (pos >= end) return null;
            byte b = data[pos++];
            u |= (ulong)(b & 0x7F) << shift;
            if ((b & 0x80) == 0)
            {
                // Zigzag decode
                return (long)(u >> 1) ^ -(long)(u & 1);
            }
            shift += 7;
            if (shift >= 64) return null;
        }
        return null;
    }

    // ═══ Size estimation ══════════════════════════════════════════════════

    private static int EstimateNumberSize(JsonElement v)
    {
        if (v.TryGetInt64(out _)) return 1 + Leb128Len(v.GetInt64());
        return 9; // TAG_FLOAT + f64
    }

    private static int EstimateStringSize(string s)
    {
        var id = Dict.LookupId(s);
        if (id.HasValue) return 2;
        var utf8Len = Utf8.GetByteCount(s);
        return 1 + Hyb128.EncodedLen((ulong)utf8Len) + utf8Len;
    }

    private static int EstimateArraySize(JsonElement v)
    {
        int len = v.GetArrayLength();
        int sz = 1 + Hyb128.EncodedLen((ulong)len);
        foreach (var item in v.EnumerateArray())
            sz += CompressedSize(item);
        return sz;
    }

    private static int EstimateObjectSize(JsonElement v)
    {
        int count = 0;
        foreach (var _ in v.EnumerateObject()) count++;
        int sz = 1 + Hyb128.EncodedLen((ulong)count);
        foreach (var prop in v.EnumerateObject())
        {
            sz += 1 + KeySize(prop.Name); // key
            sz += CompressedSize(prop.Value);
        }
        return sz;
    }

    private static int KeySize(string key)
    {
        var id = Dict.LookupId(key);
        if (id.HasValue) return 0; // key already accounts for 1 byte
        return 1 + Hyb128.EncodedLen((ulong)Utf8.GetByteCount(key)) + Utf8.GetByteCount(key);
    }

    private static int Leb128Len(long v)
    {
        ulong u = ((ulong)v << 1) ^ (ulong)(v >> 63);
        int len = 0;
        do { len++; u >>= 7; } while (u > 0);
        return len;
    }
}

/// <summary>
/// Reusable buffer backed by ArrayPool for zero-alloc encoding.
/// </summary>
internal sealed class ArrayPoolBuffer : IDisposable
{
    private byte[] _buf;
    private int _pos;

    public ArrayPoolBuffer(int initialCapacity = 256)
    {
        _buf = ArrayPool<byte>.Shared.Rent(initialCapacity);
    }

    public void WriteByte(byte b)
    {
        Ensure(1);
        _buf[_pos++] = b;
    }

    public void WriteBytes(ReadOnlySpan<byte> bytes)
    {
        Ensure(bytes.Length);
        bytes.CopyTo(_buf.AsSpan(_pos));
        _pos += bytes.Length;
    }

    public byte[] ToArray() => _buf.AsSpan(0, _pos).ToArray();
    public ReadOnlySpan<byte> Written => _buf.AsSpan(0, _pos);

    private void Ensure(int extra)
    {
        if (_pos + extra <= _buf.Length) return;
        var newBuf = ArrayPool<byte>.Shared.Rent(Math.Max(_buf.Length * 2, _pos + extra));
        _buf.AsSpan(0, _pos).CopyTo(newBuf);
        ArrayPool<byte>.Shared.Return(_buf);
        _buf = newBuf;
    }

    public void Dispose()
    {
        if (_buf.Length > 0)
        {
            ArrayPool<byte>.Shared.Return(_buf);
            _buf = Array.Empty<byte>();
        }
    }
}
