using System.Runtime.InteropServices;
using System.Text.Json;

namespace Lumen;

/// <summary>
/// P/Invoke FFI wrapper for the Rust lumen.dll.
/// Compress path: JSON string → Rust → LUMEN binary (4× faster than native C#).
/// </summary>
public static class LumenFFI
{
    private const string DllName =
#if WINDOWS
        "lumen.dll";
#elif LINUX
        "liblumen.so";
#elif OSX
        "liblumen.dylib";
#else
        "lumen";
#endif

    // ═══ P/Invoke declarations ════════════════════════════════════════════

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    private static extern int lumen_compress(
        byte[] jsonPtr, nuint jsonLen,
        out nint outPtr, out nuint outLen);

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    private static extern int lumen_decompress(
        byte[] dataPtr, nuint dataLen,
        out nint outPtr, out nuint outLen);

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    private static extern void lumen_free(nint ptr, nuint len);

    // ═══ Public API ═══════════════════════════════════════════════════════

    /// <summary>Compress a JSON element into LUMEN binary via Rust FFI.</summary>
    public static byte[] CompressValue(JsonElement value)
    {
        var json = JsonSerializer.Serialize(value);
        return CompressJson(json);
    }

    /// <summary>Compress a JSON string into LUMEN binary via Rust FFI.</summary>
    public static byte[] CompressJson(string json)
    {
        var jsonBytes = System.Text.Encoding.UTF8.GetBytes(json);
        int rc = lumen_compress(jsonBytes, (nuint)jsonBytes.Length, out var ptr, out var len);
        if (rc != 0)
            throw new InvalidOperationException("lumen_compress failed");

        var result = new byte[(int)len];
        Marshal.Copy(ptr, result, 0, (int)len);
        lumen_free(ptr, len);
        return result;
    }

    /// <summary>Decompress LUMEN binary → JSON element via Rust FFI.</summary>
    public static JsonElement? DecompressValue(byte[] data)
    {
        int rc = lumen_decompress(data, (nuint)data.Length, out var ptr, out var len);
        if (rc != 0)
            throw new InvalidOperationException("lumen_decompress failed");

        var jsonBytes = new byte[(int)len];
        Marshal.Copy(ptr, jsonBytes, 0, (int)len);
        lumen_free(ptr, len);

        var json = System.Text.Encoding.UTF8.GetString(jsonBytes);
        return JsonSerializer.Deserialize<JsonElement>(json);
    }
}
