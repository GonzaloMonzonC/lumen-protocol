"""
LUMEN e2e cross-implementation test runner — Python.
=====================================================

Generates golden binary files from shared test vectors and validates
compress/decompress roundtrips. Other implementations verify against
these golden binaries.

Run: python tests/e2e/run_e2e.py
"""
import json
import os
import sys
import hashlib

# Ensure the Python implementation is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "implementations", "python", "src"))

from lumen import (
    compress_value,
    decompress_value,
    FrameAssembler,
    build_frame,
    parse_frame,
    ParseComplete,
    TYPE_REQUEST,
    TYPE_RESPONSE,
    TYPE_NOTIFY,
    FLAG_COMPRESSED,
    FLAG_PRIORITY,
    encode_hyb128_bytes,
    decode_hyb128,
    HYB128_MAX_SHORT,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VECTORS_PATH = os.path.join(SCRIPT_DIR, "shared_vectors.json")
GOLDEN_DIR = os.path.join(SCRIPT_DIR, "golden")
REPORT_PATH = os.path.join(SCRIPT_DIR, "report_python.json")

os.makedirs(GOLDEN_DIR, exist_ok=True)


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def test_compress_roundtrip(vectors: list[dict]) -> list[dict]:
    """Test that compress → decompress is lossless for all vectors."""
    results = []
    for v in vectors:
        name = v["name"]
        value = v["value"]
        try:
            compressed = compress_value(value)
            decompressed = decompress_value(compressed)

            # Save golden binary
            golden_path = os.path.join(GOLDEN_DIR, f"{name}.lumen")
            with open(golden_path, "wb") as f:
                f.write(bytes(compressed))

            # Verify roundtrip
            if value is None:
                ok = decompressed is None
            elif isinstance(value, float):
                # Canonicalization: whole-number floats → TAG_INT (cross-language interop)
                if value == int(value) and -0x8000000000000000 <= int(value) <= 0x7FFFFFFFFFFFFFFF:
                    ok = isinstance(decompressed, int) and decompressed == int(value)
                else:
                    ok = isinstance(decompressed, float) and abs(value - decompressed) < 1e-12
            else:
                ok = decompressed == value

            results.append({
                "vector": name,
                "test": "compress_roundtrip",
                "pass": ok,
                "compressedSize": len(compressed),
                "compressedHash": hash_bytes(bytes(compressed)),
                "jsonSize": len(json.dumps(value, ensure_ascii=False)),
                "error": None if ok else f"mismatch: expected {value!r}, got {decompressed!r}",
            })
        except Exception as e:
            results.append({
                "vector": name,
                "test": "compress_roundtrip",
                "pass": False,
                "error": f"{type(e).__name__}: {e}",
            })
    return results


def test_hyb128_roundtrip() -> list[dict]:
    """Test Hyb128 encode/decode on boundary values."""
    results = []
    test_values = [
        (0, 1), (1, 1), (42, 1), (63, 1),        # Short mode
        (64, 3), (255, 3), (1000, 3), (65535, 3), # u16 mode
        (65536, 5), (100000, 5), (1000000, 5),     # u32 mode
    ]
    for value, expected_bytes in test_values:
        try:
            encoded = encode_hyb128_bytes(value)
            decoded = decode_hyb128(encoded, 0)
            ok = (len(encoded) == expected_bytes and
                  decoded[0] == value and
                  decoded[1] == expected_bytes)
            results.append({
                "vector": f"hyb128_{value}",
                "test": "hyb128_roundtrip",
                "pass": ok,
                "encodedLen": len(encoded),
                "expectedLen": expected_bytes,
                "decodedValue": decoded[0] if decoded else None,
                "error": None if ok else f"len mismatch: {len(encoded)} != {expected_bytes} or value mismatch",
            })
        except Exception as e:
            results.append({
                "vector": f"hyb128_{value}",
                "test": "hyb128_roundtrip",
                "pass": False,
                "error": f"{type(e).__name__}: {e}",
            })
    return results


def test_frame_roundtrip() -> list[dict]:
    """Test frame build/parse roundtrip with various payloads."""
    results = []
    payloads = [
        ("empty", b""),
        ("hello", b"hello"),
        ("json_small", json.dumps({"method": "ping"}, ensure_ascii=False, separators=(',', ':')).encode()),
        ("json_mcp", json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"}
        }, ensure_ascii=False, separators=(',', ':')).encode()),
    ]
    frame_types = [
        ("REQUEST", TYPE_REQUEST),
        ("RESPONSE", TYPE_RESPONSE),
        ("NOTIFY", TYPE_NOTIFY),
    ]
    flag_sets = [
        ("none", 0),
        ("compressed", FLAG_COMPRESSED),
        ("priority", FLAG_PRIORITY),
    ]

    for pname, payload in payloads:
        for tname, ftype in frame_types:
            for flname, flags in flag_sets:
                name = f"frame_{tname}_{flname}_{pname}"
                try:
                    frame = build_frame(ftype, flags, payload)
                    wire = frame.to_bytes()

                    # Save golden
                    golden_path = os.path.join(GOLDEN_DIR, f"{name}.frame")
                    with open(golden_path, "wb") as f:
                        f.write(wire)

                    result = parse_frame(wire, 0)
                    ok = (isinstance(result, ParseComplete) and
                          result.frame.frame_type == ftype and
                          result.frame.flags == flags and
                          result.frame.payload == payload)

                    results.append({
                        "vector": name,
                        "test": "frame_roundtrip",
                        "pass": ok,
                        "wireSize": len(wire),
                        "wireHash": hash_bytes(wire),
                        "payloadSize": len(payload),
                        "error": None if ok else f"frame parse mismatch",
                    })
                except Exception as e:
                    results.append({
                        "vector": name,
                        "test": "frame_roundtrip",
                        "pass": False,
                        "error": f"{type(e).__name__}: {e}",
                    })
    return results


def test_frame_assembler() -> list[dict]:
    """Test FrameAssembler streaming reassembly."""
    results = []

    # Single frame
    try:
        assembler = FrameAssembler()
        frame = build_frame(TYPE_RESPONSE, 0, b"hello")
        frames = assembler.push(frame.to_bytes())
        ok = len(frames) == 1 and frames[0].payload == b"hello"
        results.append({
            "vector": "assembler_single",
            "test": "frame_assembler",
            "pass": ok,
            "error": None if ok else "single frame reassembly failed",
        })
    except Exception as e:
        results.append({"vector": "assembler_single", "test": "frame_assembler", "pass": False, "error": str(e)})

    # Multiple frames in one chunk
    try:
        assembler = FrameAssembler()
        f1 = build_frame(TYPE_NOTIFY, 0, b"A")
        f2 = build_frame(TYPE_RESPONSE, 0, b"BB")
        wire = f1.to_bytes() + f2.to_bytes()
        frames = assembler.push(wire)
        ok = len(frames) == 2 and frames[0].payload == b"A" and frames[1].payload == b"BB"
        results.append({
            "vector": "assembler_multi",
            "test": "frame_assembler",
            "pass": ok,
            "error": None if ok else "multi-frame reassembly failed",
        })
    except Exception as e:
        results.append({"vector": "assembler_multi", "test": "frame_assembler", "pass": False, "error": str(e)})

    # Chunked delivery (split frame across pushes)
    try:
        assembler = FrameAssembler()
        frame = build_frame(TYPE_REQUEST, FLAG_COMPRESSED, b"chunked_test")
        wire = frame.to_bytes()
        mid = len(wire) // 2
        r1 = assembler.push(wire[:mid])
        r2 = assembler.push(wire[mid:])
        all_frames = r1 + r2
        ok = len(all_frames) == 1 and all_frames[0].payload == b"chunked_test"
        results.append({
            "vector": "assembler_chunked",
            "test": "frame_assembler",
            "pass": ok,
            "error": None if ok else "chunked reassembly failed",
        })
    except Exception as e:
        results.append({"vector": "assembler_chunked", "test": "frame_assembler", "pass": False, "error": str(e)})

    # Reset functionality
    try:
        assembler = FrameAssembler()
        frame = build_frame(TYPE_RESPONSE, 0, b"hello")
        assembler.push(frame.to_bytes()[:2])
        assert len(assembler) > 0
        assembler.reset()
        assert len(assembler) == 0
        frames = assembler.push(frame.to_bytes())
        ok = len(frames) == 1
        results.append({
            "vector": "assembler_reset",
            "test": "frame_assembler",
            "pass": ok,
            "error": None if ok else "reset failed",
        })
    except Exception as e:
        results.append({"vector": "assembler_reset", "test": "frame_assembler", "pass": False, "error": str(e)})

    return results


def test_compressed_frame_integration() -> list[dict]:
    """Test full integration: compress payload → wrap in frame → parse → decompress."""
    results = []
    payloads = [
        ("initialize", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2025-06-18"}}),
        ("tools_list", {"jsonrpc": "2.0", "id": 2, "result": {
            "tools": [{"name": "search", "description": "Search code",
                        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}}]
        }}),
    ]

    for pname, payload in payloads:
        name = f"integration_{pname}"
        try:
            # Compress payload
            compressed = compress_value(payload)
            # Wrap in frame
            frame = build_frame(TYPE_REQUEST, FLAG_COMPRESSED, bytes(compressed))
            wire = frame.to_bytes()

            # Save golden
            golden_path = os.path.join(GOLDEN_DIR, f"{name}.frame")
            with open(golden_path, "wb") as f:
                f.write(wire)

            # Parse frame
            result = parse_frame(wire, 0)
            ok_frame = isinstance(result, ParseComplete) and result.frame.flags == FLAG_COMPRESSED

            # Decompress payload
            decompressed = decompress_value(result.frame.payload)
            ok_decompress = decompressed == payload

            ok = ok_frame and ok_decompress
            results.append({
                "vector": name,
                "test": "compressed_frame_integration",
                "pass": ok,
                "wireSize": len(wire),
                "wireHash": hash_bytes(wire),
                "error": None if ok else "integration failed",
            })
        except Exception as e:
            results.append({
                "vector": name,
                "test": "compressed_frame_integration",
                "pass": False,
                "error": f"{type(e).__name__}: {e}",
            })

    return results


def test_cross_implementation_binary_stability() -> list[dict]:
    """Verify that compressing the same value twice produces identical binary.
    This is critical for cross-implementation compatibility."""
    results = []
    for v in [
        ("null", None),
        ("bool", True),
        ("int", 42),
        ("float", 3.14),
        ("string", "hello"),
        ("array", [1, 2, 3]),
        ("object", {"key": "value"}),
        ("mcp_init", {"jsonrpc": "2.0", "method": "initialize"}),
    ]:
        name = f"stability_{v[0]}"
        try:
            c1 = bytes(compress_value(v[1]))
            c2 = bytes(compress_value(v[1]))
            ok = c1 == c2
            results.append({
                "vector": name,
                "test": "binary_stability",
                "pass": ok,
                "hash": hash_bytes(c1),
                "error": None if ok else "non-deterministic compression",
            })
        except Exception as e:
            results.append({
                "vector": name,
                "test": "binary_stability",
                "pass": False,
                "error": str(e),
            })
    return results


def main():
    with open(VECTORS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    vectors = data["vectors"]

    print(f"LUMEN e2e — Python runner")
    print(f"  Vectors: {len(vectors)}")
    print(f"  Golden dir: {GOLDEN_DIR}")
    print()

    all_results = []
    all_results.extend(test_compress_roundtrip(vectors))
    all_results.extend(test_hyb128_roundtrip())
    all_results.extend(test_frame_roundtrip())
    all_results.extend(test_frame_assembler())
    all_results.extend(test_compressed_frame_integration())
    all_results.extend(test_cross_implementation_binary_stability())

    passed = sum(1 for r in all_results if r["pass"])
    failed = sum(1 for r in all_results if not r["pass"])

    print(f"Results: {passed} passed, {failed} failed, {len(all_results)} total")
    print()

    if failed:
        print("FAILURES:")
        for r in all_results:
            if not r["pass"]:
                print(f"  [{r['vector']}] {r['test']}: {r.get('error', 'unknown')}")

    # Write JSON report for other implementations to consume
    report = {
        "implementation": "python",
        "passed": passed,
        "failed": failed,
        "total": len(all_results),
        "results": all_results,
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nReport written to {REPORT_PATH}")
    print(f"Golden binaries in {GOLDEN_DIR}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
