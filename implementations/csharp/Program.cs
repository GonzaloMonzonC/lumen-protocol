using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace Lumen;

class Program
{
    // ═══ Benchmark fixtures (matching Python/Node benchmarks) ═══════════

    private static readonly JsonElement SmallVal = JsonSerializer.SerializeToElement(
        new { jsonrpc = "2.0", id = 1, method = "tools/list" });

    private static readonly JsonElement InitVal = JsonSerializer.SerializeToElement(new
    {
        jsonrpc = "2.0", id = 1, method = "initialize",
        @params = new
        {
            protocolVersion = "2025-06-18",
            capabilities = new { roots = new { listChanged = true }, sampling = new { } }
        }
    });

    private static readonly JsonElement ToolsVal = JsonSerializer.SerializeToElement(new
    {
        jsonrpc = "2.0", id = 2,
        result = new
        {
            tools = Enumerable.Range(0, 20).Select(i => new
            {
                name = $"tool_{i}",
                description = $"Tool {i} description here",
                inputSchema = new
                {
                    type = "object",
                    properties = new
                    {
                        query = new { type = "string", description = "Search query" },
                        limit = new { type = "integer", description = "Max results" },
                        verbose = new { type = "boolean" }
                    }
                }
            })
        }
    });

    private static readonly JsonElement LlmVal = JsonSerializer.SerializeToElement(new
    {
        jsonrpc = "2.0", id = 3,
        result = new
        {
            content = new[] { new { type = "text", text = "def hello():\n    print('Hello world')\n\ndef goodbye():\n    print('Bye')" } },
            model = "claude-4",
            usage = new { input_tokens = 150, output_tokens = 85 }
        }
    });

    // ═══ Entry point ═════════════════════════════════════════════════════

    static void Main(string[] args)
    {
        Console.WriteLine("=== LUMEN C# — P/Invoke FFI ===\n");

        // 1. Roundtrip tests
        RunRoundtripTests();

        // 2. Golden binary compatibility
        RunGoldenTests();

        // 3. Performance benchmark
        RunBenchmark();

        Console.WriteLine("\nDone.");
    }

    // ═══ 1. Roundtrip tests ═══════════════════════════════════════════════

    static void RunRoundtripTests()
    {
        Console.WriteLine("── Roundtrip Tests ──");
        var cases = new (string name, JsonElement val)[]
        {
            ("null", JsonSerializer.SerializeToElement<object?>(null)),
            ("bool_true", JsonSerializer.SerializeToElement(true)),
            ("bool_false", JsonSerializer.SerializeToElement(false)),
            ("int_zero", JsonSerializer.SerializeToElement(0)),
            ("int_small", JsonSerializer.SerializeToElement(42)),
            ("int_negative", JsonSerializer.SerializeToElement(-7)),
            ("int_large", JsonSerializer.SerializeToElement(int.MaxValue)),
            ("float_pi", JsonSerializer.SerializeToElement(3.14)),
            ("string_short", JsonSerializer.SerializeToElement("hello")),
            ("string_unicode", JsonSerializer.SerializeToElement("héllo 世界")),
            ("array_ints", JsonSerializer.SerializeToElement(new[] { 1, 2, 3 })),
            ("array_nested", JsonSerializer.SerializeToElement(new object[] { new[] { 1 }, new { a = 1 } })),
            ("object_simple", JsonSerializer.SerializeToElement(new { key = "value" })),
            ("object_nested", JsonSerializer.SerializeToElement(new { outer = new { inner = 1 } })),
            ("mcp_initialize", InitVal),
            ("mcp_tools_list", SmallVal),
            ("mcp_error_response", JsonSerializer.SerializeToElement(new { jsonrpc = "2.0", id = 5, error = new { code = -32601, message = "Method not found" } })),
        };

        int passed = 0;
        foreach (var (name, val) in cases)
        {
            try
            {
                var compressed = LumenCompress.CompressValue(val);
                var decompressed = LumenCompress.DecompressValue(compressed);
                if (decompressed is null)
                {
                    Console.WriteLine($"  FAIL {name}: decompress returned null");
                    continue;
                }
                var reJson = JsonSerializer.Serialize(decompressed.Value);
                var origJson = JsonSerializer.Serialize(val);
                if (reJson == origJson)
                {
                    passed++;
                }
                else
                {
                    Console.WriteLine($"  FAIL {name}: {origJson} → {reJson}");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"  FAIL {name}: {ex.Message}");
            }
        }
        Console.WriteLine($"  {passed}/{cases.Length} roundtrip tests passed\n");

        // FFI roundtrips
        Console.WriteLine("── FFI Roundtrip Tests ──");
        int ffiPassed = 0;
        foreach (var (name, val) in cases)
        {
            try
            {
                var compressed = LumenFFI.CompressValue(val);
                var decompressed = LumenFFI.DecompressValue(compressed);
                if (decompressed is null)
                {
                    Console.WriteLine($"  FAIL FFI {name}: decompress returned null");
                    continue;
                }
                var reJson = JsonSerializer.Serialize(decompressed.Value);
                var origJson = JsonSerializer.Serialize(val);
                if (reJson == origJson)
                {
                    // Also cross-check: C# native decompress of FFI output
                    var csDecomp = LumenCompress.DecompressValue(compressed);
                    var csJson = JsonSerializer.Serialize(csDecomp!.Value);
                    if (csJson == origJson) ffiPassed++;
                    else Console.WriteLine($"  FAIL cross {name}: C# native → {csJson}");
                }
                else
                {
                    Console.WriteLine($"  FAIL FFI {name}: {origJson} → {reJson}");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"  FAIL FFI {name}: {ex.Message}");
            }
        }
        Console.WriteLine($"  {ffiPassed}/{cases.Length} FFI roundtrip + cross-check tests passed\n");
    }

    // ═══ 2. Golden binary compatibility ═══════════════════════════════════

    static void RunGoldenTests()
    {
        Console.WriteLine("── Golden Binary Compatibility ──");
        var goldenDir = Path.Combine(
            AppDomain.CurrentDomain.BaseDirectory,
            "..", "..", "..", "..", "..", "tests", "e2e", "golden");

        if (!Directory.Exists(goldenDir))
        {
            // Try relative to csharp dir
            goldenDir = Path.Combine(
                AppDomain.CurrentDomain.BaseDirectory,
                "..", "..", "..", "..", "tests", "e2e", "golden");
        }

        if (!Directory.Exists(goldenDir))
        {
            Console.WriteLine($"  SKIP: golden directory not found at {goldenDir}");
            return;
        }

        var sharedVectorsPath = Path.Combine(
            Path.GetDirectoryName(goldenDir)!, "shared_vectors.json");

        if (!File.Exists(sharedVectorsPath))
        {
            Console.WriteLine("  SKIP: shared_vectors.json not found");
            return;
        }

        var sharedVectors = JsonSerializer.Deserialize<JsonElement>(
            File.ReadAllText(sharedVectorsPath));
        var vectors = sharedVectors.GetProperty("vectors").EnumerateArray().ToArray();

        int ok = 0, fail = 0;
        foreach (var vec in vectors)
        {
            var name = vec.GetProperty("name").GetString()!;
            var goldenPath = Path.Combine(goldenDir, $"{name}.lumen");
            if (!File.Exists(goldenPath)) continue;

            try
            {
                var golden = File.ReadAllBytes(goldenPath);

                // C# native compress must match golden byte-for-byte
                var val = vec.GetProperty("value");
                var compressed = LumenCompress.CompressValue(val);

                if (compressed.SequenceEqual(golden))
                {
                    ok++;
                }
                else
                {
                    fail++;
                    Console.WriteLine($"  FAIL {name}:");
                    Console.WriteLine($"    golden: {BitConverter.ToString(golden)}");
                    Console.WriteLine($"    C#:     {BitConverter.ToString(compressed)}");
                }
            }
            catch (Exception ex)
            {
                fail++;
                Console.WriteLine($"  FAIL {name}: {ex.Message}");
            }
        }

        // Also test FFI golden compat
        int ffiOk = 0, ffiFail = 0;
        foreach (var vec in vectors)
        {
            var name = vec.GetProperty("name").GetString()!;
            var goldenPath = Path.Combine(goldenDir, $"{name}.lumen");
            if (!File.Exists(goldenPath)) continue;

            try
            {
                var golden = File.ReadAllBytes(goldenPath);
                var val = vec.GetProperty("value");
                var ffiCompressed = LumenFFI.CompressValue(val);

                if (ffiCompressed.SequenceEqual(golden))
                    ffiOk++;
                else
                {
                    ffiFail++;
                    Console.WriteLine($"  FAIL FFI {name}:");
                    Console.WriteLine($"    golden: {BitConverter.ToString(golden)}");
                    Console.WriteLine($"    FFI:    {BitConverter.ToString(ffiCompressed)}");
                }
            }
            catch (Exception ex)
            {
                ffiFail++;
                Console.WriteLine($"  FAIL FFI {name}: {ex.Message}");
            }
        }

        Console.WriteLine($"  C# native: {ok} passed, {fail} failed");
        Console.WriteLine($"  P/Invoke:  {ffiOk} passed, {ffiFail} failed\n");
    }

    // ═══ 3. Performance benchmark ═════════════════════════════════════════

    static void RunBenchmark()
    {
        Console.WriteLine("── Performance Benchmark ──");
        Console.WriteLine($"  .NET {Environment.Version}");
        Console.WriteLine();

        var cases = new (string label, JsonElement val, int iters)[]
        {
            ("MCP tools/list", SmallVal, 5000),
            ("MCP initialize", InitVal, 5000),
            ("MCP tools x20", ToolsVal, 1000),
            ("LLM response", LlmVal, 2000),
        };

        Console.WriteLine($"{"Payload",-22} {"Op",12} {"Native",10} {"FFI",10} {"Speedup",8}");
        Console.WriteLine(new string('-', 67));

        double totNc = 0, totFc = 0, totNd = 0, totFd = 0;

        foreach (var (label, val, iters) in cases)
        {
            // Pre-compute compressed for decompress benchmarks
            var raw = LumenCompress.CompressValue(val);
            var rawFfi = LumenFFI.CompressValue(val);
            var jsonStr = JsonSerializer.Serialize(val);

            // Compress: C# native (includes JSON serialize) vs FFI (JSON string)
            var nc = Bench(_ => LumenCompress.CompressValue(val), iters);
            var fc = Bench(_ => LumenFFI.CompressJson(jsonStr), iters);

            // Decompress
            var nd = Bench(_ => LumenCompress.DecompressValue(raw), iters);
            var fd = Bench(_ => LumenFFI.DecompressValue(rawFfi), iters);

            Console.WriteLine($"{label,-22} {"compress",12} {nc,9:F1}us {fc,9:F1}us {(nc / fc),7:F1}x");
            Console.WriteLine($"{label,-22} {"decompress",12} {nd,9:F1}us {fd,9:F1}us {(nd / fd),7:F1}x");
            totNc += nc; totFc += fc; totNd += nd; totFd += fd;
        }

        Console.WriteLine(new string('-', 67));
        Console.WriteLine($"{"TOTAL",-22} {"compress",12} {totNc,9:F1}us {totFc,9:F1}us {(totNc / totFc),7:F1}x");
        Console.WriteLine($"{"TOTAL",-22} {"decompress",12} {totNd,9:F1}us {totFd,9:F1}us {(totNd / totFd),7:F1}x");
    }

    static double Bench(Action<object?> fn, int iters)
    {
        // Warmup
        for (int i = 0; i < Math.Min(iters / 5, 100); i++) fn(null);
        // Measure
        GC.Collect();
        GC.WaitForPendingFinalizers();
        var sw = Stopwatch.StartNew();
        for (int i = 0; i < iters; i++) fn(null);
        sw.Stop();
        return sw.Elapsed.TotalMicroseconds / iters;
    }
}

static class StopwatchExt
{
    public static double TotalMicroseconds(this TimeSpan ts) =>
        ts.TotalMilliseconds * 1000.0;
}
