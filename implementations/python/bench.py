"""LUMEN Python Benchmark Suite - mirrors TypeScript bench.ts."""
from __future__ import annotations
import json, sys, time, platform
from typing import Any
from lumen.hyb128 import encode_hyb128, decode_hyb128
from lumen.dict import lookup_dict_id
from lumen.compress import compress_value, decompress_value
from lumen.frame import build_frame
from lumen.frame_assembler import FrameAssembler

TYPE_REQUEST = 1


# ── Helpers ──

def timeit(runs: int, fn, warmup: int = 0) -> float:
    """Call fn() *runs* times, return elapsed milliseconds."""
    for _ in range(warmup):
        fn()
    t0 = time.perf_counter()
    for _ in range(runs):
        fn()
    return (time.perf_counter() - t0) * 1000


def make_result(name: str, category: str, ops: int, duration_ms: float,
                bytes_processed: int = 0, extra: dict | None = None) -> dict:
    ops_per_sec = round(ops / (duration_ms / 1000)) if duration_ms > 0 else 0
    bytes_per_sec = round(bytes_processed / (duration_ms / 1000)) if duration_ms > 0 else 0
    return {
        "name": name, "category": category,
        "ops": ops, "durationMs": round(duration_ms, 2),
        "opsPerSec": ops_per_sec, "bytesProcessed": bytes_processed,
        "bytesPerSec": bytes_per_sec,
        "extra": extra or {}
    }


# ── MCP fixtures ──

MCP: list[dict[str, Any]] = [
    {
        "name": "initialize",
        "obj": {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "lumen-test", "version": "1.0"}}}
    },
    {
        "name": "tools_list",
        "obj": {"jsonrpc": "2.0", "id": 2, "result": {"tools": [
            {"name": "read", "description": "Read file",
             "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
            {"name": "write", "description": "Write file",
             "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
            {"name": "delete", "description": "Delete file",
             "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
            {"name": "execute", "description": "Execute command",
             "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}, "arguments": {"type": "array"}}, "required": ["command"]}},
            {"name": "search", "description": "Search files",
             "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "path": {"type": "string"}}, "required": ["query"]}},
        ]}}
    },
    {
        "name": "llm_request",
        "obj": {"model": "gpt-4", "temperature": 0.7, "max_tokens": 4096,
                "messages": [{"role": "system", "content": "You are helpful."},
                             {"role": "user", "content": "Explain LUMEN protocol."}],
                "tools": [{"type": "function", "function": {"name": "search", "description": "Search web",
                            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}}]}
    },
    {
        "name": "error_response",
        "obj": {"jsonrpc": "2.0", "id": 5, "error": {"code": -32601, "message": "Method not found",
                 "data": {"method": "unknown_tool", "severity": "error", "details": "The requested tool does not exist"}}}
    },
    {
        "name": "big_result",
        "obj": {"jsonrpc": "2.0", "id": 8, "result": {
            "content": [{"type": "text", "text": "A" * 5000}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 5000, "total_tokens": 5120},
            "model": "deepseek-v4", "finish_reason": "stop"}}
    },
]


# ═══ A. FrameAssembler ═══

def bench_assembler() -> list[dict]:
    payloads = {"tiny": 16, "small": 256, "medium": 4096, "large": 65536, "xlarge": 262144}
    results = []
    for label, size in payloads.items():
        payload = b"A" * size
        wire = build_frame(TYPE_REQUEST, payload=payload).to_bytes()
        for chunk_hint in [1, 16, 64, 256, 1024, 4096, None]:
            csl = "full" if chunk_hint is None else str(chunk_hint)
            acs = chunk_hint if chunk_hint is not None else len(wire)
            chunks = [wire[i:i + acs] for i in range(0, len(wire), acs)]
            runs = 100 if size > 16384 else 500

            for _ in range(5):
                a = FrameAssembler()
                for c in chunks:
                    a.push(c)

            def _b(chunks=chunks):
                a = FrameAssembler()
                for c in chunks:
                    a.push(c)

            ms = timeit(runs, _b)
            total_bytes = len(wire) * runs
            results.append(make_result(
                f"FrameAssembler {label}({size}B) chunk={csl}", "assembler",
                runs, ms, total_bytes,
                {"payloadSize": size, "chunkSize": acs if csl != "full" else "full", "numChunks": len(chunks)}
            ))
    return results


# ═══ B. Compression ratio ═══

def bench_compression() -> list[dict]:
    results = []
    for e in MCP:
        name, obj = e["name"], e["obj"]
        json_bytes = len(json.dumps(obj).encode())

        def _b(obj=obj):
            compress_value(obj)

        ms = timeit(1000, _b, warmup=50)
        compressed = compress_value(obj)
        cb = len(compressed)
        ratio = round(cb / json_bytes * 100, 1)
        results.append(make_result(
            f"Compress {name}", "compression", 1000, ms, json_bytes * 1000,
            {"objectName": name, "jsonBytes": json_bytes, "compressedBytes": cb,
             "ratioPercent": ratio, "savedBytes": json_bytes - cb}
        ))
    return results


# ═══ C. Hyb128 ═══

def bench_hyb128() -> list[dict]:
    vals = [0, 1, 31, 63, 64, 255, 1000, 65535, 65536, 100000, 1000000]
    results = []

    for v in vals:
        buf = bytearray(11)

        def _b(v=v, buf=buf):
            encode_hyb128(v, buf, 0)

        ms = timeit(100_000, _b, warmup=500)
        mode = "00" if v <= 63 else "10" if v <= 65535 else "11"
        results.append(make_result(
            f"encodeHyb128({v})", "hyb128_encode", 100_000, ms,
            extra={"value": v, "mode": mode}
        ))

    for v in vals:
        buf = bytearray(11)
        el = encode_hyb128(v, buf, 0)
        enc = bytes(buf[:el])

        def _b(enc=enc):
            decode_hyb128(enc, 0)

        ms = timeit(100_000, _b, warmup=500)
        results.append(make_result(
            f"decodeHyb128({v})", "hyb128_decode", 100_000, ms,
            extra={"value": v, "headerBytes": el}
        ))

    return results


# ═══ D. Dict ═══

def bench_dict() -> list[dict]:
    keys = ["tool", "arguments", "result", "error", "id", "name",
            "description", "content", "text", "type", "method", "params",
            "jsonrpc", "data", "code", "message"]
    N = 1_000_000

    def _b():
        for i in range(N):
            lookup_dict_id(keys[i % len(keys)])

    ms = timeit(1, _b)
    return [make_result("dict_lookup O(1)", "dict", N, ms, extra={"totalKeys": len(keys)})]


# ═══ E. Encode ═══

def bench_encode() -> list[dict]:
    results = []
    for e in MCP:
        name, obj = e["name"], e["obj"]
        json_bytes = len(json.dumps(obj).encode())
        comp = compress_value(obj)

        def _json(obj=obj):
            json.dumps(obj)

        jms = timeit(5000, _json, warmup=50)
        jops = round(5000 / (jms / 1000)) if jms > 0 else 0

        def _lumen(obj=obj):
            compress_value(obj)

        lms = timeit(5000, _lumen, warmup=50)
        lops = round(5000 / (lms / 1000)) if lms > 0 else 0
        speedup = round(lops / jops, 2) if jops > 0 else 0

        results.append(make_result(
            f"Encode json.dumps {name}", "json_encode", 5000, jms, json_bytes * 5000,
            {"objectName": name, "jsonBytes": json_bytes}
        ))
        results.append(make_result(
            f"Encode compress_value {name}", "lumen_encode", 5000, lms, len(comp) * 5000,
            {"objectName": name, "compressedBytes": len(comp), "speedupVsJson": speedup}
        ))
    return results


# ═══ F. Decode ═══

def bench_decode() -> list[dict]:
    prepared = [{"name": e["name"], "js": json.dumps(e["obj"]), "comp": compress_value(e["obj"])} for e in MCP]
    results = []
    for p in prepared:
        name, js, comp = p["name"], p["js"], p["comp"]
        json_bytes = len(js.encode())

        def _json(js=js):
            json.loads(js)

        jms = timeit(5000, _json, warmup=50)
        jops = round(5000 / (jms / 1000)) if jms > 0 else 0

        def _lumen(comp=comp):
            decompress_value(comp)

        lms = timeit(5000, _lumen, warmup=50)
        lops = round(5000 / (lms / 1000)) if lms > 0 else 0
        speedup = round(lops / jops, 2) if jops > 0 else 0

        results.append(make_result(
            f"Decode json.loads {name}", "json_decode", 5000, jms, json_bytes * 5000,
            {"objectName": name, "jsonBytes": json_bytes}
        ))
        results.append(make_result(
            f"Decode decompress_value {name}", "lumen_decode", 5000, lms, len(comp) * 5000,
            {"objectName": name, "compressedBytes": len(comp), "speedupVsJson": speedup}
        ))
    return results


# ═══ G. Roundtrip ═══

def bench_roundtrip() -> list[dict]:
    results = []
    for e in MCP:
        name, obj = e["name"], e["obj"]
        json_bytes = len(json.dumps(obj).encode())
        comp = compress_value(obj)

        def _json_rt(obj=obj):
            json.loads(json.dumps(obj))

        jms = timeit(5000, _json_rt, warmup=50)
        jops = round(5000 / (jms / 1000)) if jms > 0 else 0

        def _lumen_rt(obj=obj):
            decompress_value(compress_value(obj))

        lms = timeit(5000, _lumen_rt, warmup=50)
        lops = round(5000 / (lms / 1000)) if lms > 0 else 0
        speedup = round(lops / jops, 2) if jops > 0 else 0

        results.append(make_result(
            f"Roundtrip JSON {name}", "json_roundtrip", 5000, jms, json_bytes * 2 * 5000,
            {"objectName": name, "jsonBytes": json_bytes}
        ))
        results.append(make_result(
            f"Roundtrip LUMEN {name}", "lumen_roundtrip", 5000, lms, len(comp) * 2 * 5000,
            {"objectName": name, "compressedBytes": len(comp), "speedupVsJson": speedup}
        ))
    return results


# ═══ I. Session Dictionary ═══

def bench_session_dict() -> list[dict]:
    from lumen.dict import init_session_dict, register_session_key, clear_session_dict
    results = []
    runs = 500

    # Register 127 custom keys (0x80–0xFE)
    init_session_dict([])
    custom_keys = [f"custom_key_{i:03d}" for i in range(127)]
    for i, key in enumerate(custom_keys):
        register_session_key(key, 0x80 + i)

    # Build payload with all 127 session keys
    payload = {key: i for i, key in enumerate(custom_keys)}
    json_str = json.dumps(payload, ensure_ascii=False)
    json_bytes = len(json_str.encode("utf-8"))

    # Compress benchmark
    compress_ms = timeit(runs, lambda: compress_value(payload), warmup=20)
    comp = compress_value(payload)

    # Decompress benchmark
    decompress_ms = timeit(runs, lambda: decompress_value(comp), warmup=20)

    ratio = round(len(comp) / json_bytes * 100, 1)
    wire_sav = round(100 - ratio, 1)

    results.append(make_result(
        "SessionDict compress (127 keys)", "session_dict", runs, compress_ms, json_bytes * runs,
        {"jsonBytes": json_bytes, "compressedBytes": len(comp), "ratioPercent": ratio, "wireSavingsPercent": wire_sav}
    ))
    results.append(make_result(
        "SessionDict decompress (127 keys)", "session_dict", runs, decompress_ms, len(comp) * runs,
        {"jsonBytes": json_bytes, "compressedBytes": len(comp)}
    ))

    # Clean up
    clear_session_dict()
    return results


# ═══ H. Framing ═══

def bench_framing() -> list[dict]:
    results = []
    test_vals = [0, 42, 255, 1024, 65535, 65536, 100000, 1000000]

    for v in test_vals:
        cl = f"Content-Length: {v}\r\n\r\n"

        def _cl(cl=cl):
            prefix = "Content-Length: "
            if not cl.startswith(prefix):
                return None
            end = cl.find("\r\n", len(prefix))
            if end == -1:
                return None
            return int(cl[len(prefix):end])

        ms = timeit(500_000, _cl, warmup=100)
        results.append(make_result(
            f"Framing Content-Length({v})", "framing_cl", 500_000, ms, len(cl) * 500_000,
            {"headerValue": v, "headerBytes": len(cl)}
        ))

        buf = bytearray(11)
        el = encode_hyb128(v, buf, 0)
        enc = bytes(buf[:el])

        def _hyb(enc=enc):
            decode_hyb128(enc, 0)

        ms = timeit(500_000, _hyb, warmup=100)
        results.append(make_result(
            f"Framing Hyb128({v})", "framing_hyb128", 500_000, ms, len(enc) * 500_000,
            {"headerValue": v, "headerBytes": len(enc)}
        ))

    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  Runner
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import os
    all_results: list[dict] = []

    benchmarks = [
        ("assembler", bench_assembler),
        ("compression", bench_compression),
        ("hyb128", bench_hyb128),
        ("dict", bench_dict),
        ("encode", bench_encode),
        ("decode", bench_decode),
        ("roundtrip", bench_roundtrip),
        ("framing", bench_framing),
        ("session_dict", bench_session_dict),
    ]

    total = len(benchmarks)
    for i, (name, fn) in enumerate(benchmarks):
        print(f"[{i + 1}/{total}] Running {name}...", file=sys.stderr)
        try:
            results = fn()
            all_results.extend(results)
            print(f"       {len(results)} results", file=sys.stderr)
        except Exception as exc:
            print(f"       SKIPPED: {exc}", file=sys.stderr)

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "platform": platform.platform(),
        "pythonVersion": platform.python_version(),
        "results": all_results,
    }

    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    print(f"\nDone. {len(all_results)} total results.", file=sys.stderr)


if __name__ == "__main__":
    main()
