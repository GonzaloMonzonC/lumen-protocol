"""Benchmark: Python native vs Rust FFI for compress/decompress."""
import ctypes, json, sys, time, gc, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'implementations', 'python', 'src'))
from lumen.compress import compress_value, decompress_value

# ── Load DLL ──
base = os.path.dirname(__file__)
dll = ctypes.CDLL(os.path.join(base, 'implementations', 'rust', 'target', 'release', 'lumen.dll'))
dll.lumen_compress.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
                               ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)), ctypes.POINTER(ctypes.c_size_t)]
dll.lumen_compress.restype = ctypes.c_int32
dll.lumen_decompress.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
                                 ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)), ctypes.POINTER(ctypes.c_size_t)]
dll.lumen_decompress.restype = ctypes.c_int32
dll.lumen_free.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t]
dll.lumen_free.restype = None


def ffi_compress(j):
    arr = (ctypes.c_uint8 * len(j))(*j)
    out = ctypes.POINTER(ctypes.c_uint8)()
    ol = ctypes.c_size_t()
    dll.lumen_compress(arr, len(j), ctypes.byref(out), ctypes.byref(ol))
    r = ctypes.string_at(out, ol.value)
    dll.lumen_free(out, ol)
    return r


def ffi_decompress(d):
    arr = (ctypes.c_uint8 * len(d))(*d)
    out = ctypes.POINTER(ctypes.c_uint8)()
    ol = ctypes.c_size_t()
    dll.lumen_decompress(arr, len(d), ctypes.byref(out), ctypes.byref(ol))
    r = ctypes.string_at(out, ol.value)
    dll.lumen_free(out, ol)
    return r


def bench(fn, data, iters):
    gc.disable()
    for _ in range(min(iters // 5, 100)):
        fn(data)
    t0 = time.perf_counter()
    for _ in range(iters):
        fn(data)
    t = time.perf_counter() - t0
    gc.enable()
    return (t / iters) * 1_000_000


# ── Fixtures ──
small_val = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
small_j = json.dumps(small_val).encode()

init_val = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18",
               "capabilities": {"roots": {"listChanged": True}, "sampling": {}}}
}
init_j = json.dumps(init_val).encode()

tools_val = {
    "jsonrpc": "2.0", "id": 2, "result": {"tools": [
        {"name": f"tool_{i}", "description": f"Tool {i} description here",
         "inputSchema": {"type": "object", "properties": {
             "query": {"type": "string", "description": "Search query"},
             "limit": {"type": "integer", "description": "Max results"},
             "verbose": {"type": "boolean"}
         }}}
        for i in range(20)
    ]}
}
tools_j = json.dumps(tools_val).encode()

llm_val = {
    "jsonrpc": "2.0", "id": 3, "result": {
        "content": [{
            "type": "text",
            "text": "def hello():\n    print('Hello world')\n\ndef goodbye():\n    print('Bye')"
        }],
        "model": "claude-4",
        "usage": {"input_tokens": 150, "output_tokens": 85}
    }
}
llm_j = json.dumps(llm_val).encode()

cases = [
    ("MCP tools/list", small_j, 5000),
    ("MCP initialize", init_j, 5000),
    ("MCP tools x20", tools_j, 1000),
    ("LLM response", llm_j, 2000),
]

print(f"{'Payload':<20} {'Op':>12} {'Native':>10} {'FFI':>10} {'Speedup':>8}")
print("-" * 65)
tot_nc = tot_fc = tot_nd = tot_fd = 0.0
for label, jbytes, iters in cases:
    val = json.loads(jbytes)
    raw = compress_value(val)

    # Compress
    nc = bench(lambda d: compress_value(json.loads(d)), jbytes, iters)
    fc = bench(ffi_compress, jbytes, iters)
    # Decompress
    nd = bench(decompress_value, raw, iters)
    fd = bench(ffi_decompress, raw, iters)

    print(f"{label:<20} {'compress':>12} {nc:>9.1f}us {fc:>9.1f}us {nc/fc:>7.1f}x")
    print(f"{label:<20} {'decompress':>12} {nd:>9.1f}us {fd:>9.1f}us {nd/fd:>7.1f}x")
    tot_nc += nc; tot_fc += fc; tot_nd += nd; tot_fd += fd

print("-" * 65)
print(f"{'TOTAL':<20} {'compress':>12} {tot_nc:>9.1f}us {tot_fc:>9.1f}us {tot_nc/tot_fc:>7.1f}x")
print(f"{'TOTAL':<20} {'decompress':>12} {tot_nd:>9.1f}us {tot_fd:>9.1f}us {tot_nd/tot_fd:>7.1f}x")
