"""
LUMEN Native Server — Inline Test (no subprocess, same process).
Runs process_message() on synthetic LUMEN frames.
"""

from __future__ import annotations

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'python', 'src'))

from lumen import build_frame, parse_frame, compress_value, decompress_value, ParseComplete
from lumen import TYPE_REQUEST, TYPE_RESPONSE, FLAG_COMPRESSED, build_size

# Import the server's shared tools and handlers locally (not hardcoded path)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(REPO_ROOT, 'implementations', 'mcp-servers', 'filesystem'))
import shared_tools
# The process_message function is in server_native.py directly
import importlib.util
server_spec = importlib.util.spec_from_file_location(
    "server_native",
    os.path.join(REPO_ROOT, 'implementations', 'mcp-servers', 'filesystem', 'server_native.py')
)
server_native = importlib.util.module_from_spec(server_spec)
server_spec.loader.exec_module(server_native)

def roundtrip(msg_dict):
    """Simulate LUMEN round-trip: client builds frame → server processes → server builds frame."""
    # Client side: build request frame
    payload = compress_value(msg_dict)
    total_size = build_size(len(payload))
    buf = bytearray(total_size)
    build_frame(TYPE_REQUEST, FLAG_COMPRESSED, payload, buf, 0)
    
    # Server side: parse, process, build response
    result = parse_frame(buf, 0)
    assert isinstance(result, ParseComplete), f"Parse failed: {type(result).__name__}"
    
    frame = result.frame
    server_payload = frame.payload
    if frame.flags & FLAG_COMPRESSED:
        server_payload = decompress_value(server_payload)
    
    response = server_native.process_message(server_payload)
    
    # Server builds response frame
    if response is None:
        return None
    
    resp_payload = compress_value(response)
    resp_total = build_size(len(resp_payload))
    resp_buf = bytearray(resp_total)
    build_frame(TYPE_RESPONSE, FLAG_COMPRESSED, resp_payload, resp_buf, 0)
    
    # Client parses response
    resp_result = parse_frame(resp_buf, 0)
    assert isinstance(resp_result, ParseComplete), "Response parse failed"
    
    resp_frame = resp_result.frame
    resp_data = resp_frame.payload
    if resp_frame.flags & FLAG_COMPRESSED:
        resp_data = decompress_value(resp_data)
    
    return resp_data

# ── Test all tools ──
print("╔══════════════════════════════════════════════════════╗")
print("║     ◆  LUMEN NATIVE — INLINE ROUNDTRIP  ◆          ║")
print("╚══════════════════════════════════════════════════════╝")

# Init
r = roundtrip({"jsonrpc":"2.0","id":1,"method":"initialize",
    "params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}})
info = r['result']['serverInfo']
print(f"\n🔌 {info['name']} v{info['version']}")

# Tools
r = roundtrip({"jsonrpc":"2.0","id":2,"method":"tools/list"})
tools = r['result']['tools']
print(f"📁 {len(tools)} tools: {[t['name'] for t in tools]}")

# Test all 7
import tempfile
td = tempfile.mkdtemp()
passed = 0
total = 0

p = os.path.join(td, "test.txt")
with open(p, 'w') as f: f.write("LUMEN NATIVE TEST\nline2\nline3\n")

tests = [
    ("read_file", {"name":"read_file","arguments":{"path":p}},
     lambda r: "LUMEN" in r['result']['content'][0]['text']),
    ("write_file", {"name":"write_file","arguments":{"path":os.path.join(td,"w.txt"),"content":"OK"}},
     lambda r: "Wrote" in r['result']['content'][0]['text']),
    ("search_files", {"name":"search_files","arguments":{"pattern":"NATIVE","path":td,"target":"content"}},
     lambda r: "test.txt" in r['result']['content'][0]['text']),
    ("search_ctx", {"name":"search_with_context","arguments":{"pattern":"NATIVE","path":td,"context":1}},
     lambda r: ">>>" in r['result']['content'][0]['text']),
    ("list_dir", {"name":"list_directory","arguments":{"path":td}},
     lambda r: len(r['result']['content'][0]['text']) > 0),
    ("patch", {"name":"patch","arguments":{"path":p,"old_string":"NATIVE","new_string":"BINARY"}},
     lambda r: "Replaced" in r['result']['content'][0]['text']),
    ("read_files", {"name":"read_files","arguments":{"paths":[p, os.path.join(td,"w.txt")]}},
     lambda r: "===" in r['result']['content'][0]['text']),
]

for name, args, check in tests:
    total += 1
    try:
        msg = {"jsonrpc":"2.0","id":99,"method":"tools/call","params":args}
        r = roundtrip(msg)
        ok = r and check(r)
        passed += ok
        print(f"  {'✅' if ok else '❌'} {name}")
        if not ok:
            print(f"       Response: {str(r)[:100]}")
    except Exception as e:
        print(f"  ❌ {name}: {e}")

import shutil; shutil.rmtree(td, ignore_errors=True)

print(f"\n{'='*55}")
print(f"  🎯 {passed}/{total} PASSED")
if passed == total:
    print("  ✅ LUMEN NATIVE — ALL 7 TOOLS WORKING")
    print("  ✅ PURE BINARY FRAMES — NO JSON WRAPPER")
