#!/usr/bin/env python3
"""Test native LUMEN transport for PDBM-Lumen."""

import sys, os, json, subprocess

os.environ["PDB_PATH"] = "/tmp/test_pdb_native3.db"

proc = subprocess.Popen(
    [sys.executable, "-u", "server_native.py"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)

from lumen import (
    build_frame, build_size, parse_frame, compress_value, decompress_value,
    FLAG_COMPRESSED, TYPE_REQUEST, ParseComplete,
)


def send_lumen(data: dict) -> None:
    payload = compress_value(data)
    total_size = build_size(payload_len=len(payload))
    buf = bytearray(total_size)
    build_frame(TYPE_REQUEST, FLAG_COMPRESSED, payload, buf, 0)
    proc.stdin.write(buf)
    proc.stdin.flush()


def recv_lumen() -> dict:
    rb = bytearray()
    while True:
        b = proc.stdout.read(1)
        if not b:
            raise EOFError(f"stdout closed. stderr: {proc.stderr.read().decode()}")
        rb.extend(b)
        r = parse_frame(rb, 0)
        if isinstance(r, ParseComplete):
            if r.frame.flags & FLAG_COMPRESSED:
                return decompress_value(r.frame.payload)
            return r.frame.payload


# 1. PROBE handshake
print("Sending PROBE...")
send_lumen({"protocol": "LUMEN", "client_name": "test", "supported_versions": ["1.0"]})
ack = recv_lumen()
print(f"PROBE received: {json.dumps(ack)[:200]}")
assert ack.get("protocol") == "LUMEN", f"No protocol marker in: {ack}"

# 2. Initialize
print("Sending initialize...")
send_lumen({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
resp = recv_lumen()
name = resp["result"]["serverInfo"]["name"]
print(f"INIT: {name}")

# 3. tools/list
send_lumen({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
resp = recv_lumen()
tools = [t["name"] for t in resp["result"]["tools"]]
print(f"TOOLS ({len(tools)}): {', '.join(tools)}")

# 4. SET
send_lumen({
    "jsonrpc": "2.0", "id": 10, "method": "tools/call",
    "params": {"name": "pdb_set", "arguments": {"ns": "NATIVE", "subs": [0, "x"], "value": "val-0"}},
})
resp = recv_lumen()
assert resp.get("result"), f"SET failed: {resp}"

# 5. ORDER
send_lumen({
    "jsonrpc": "2.0", "id": 20, "method": "tools/call",
    "params": {"name": "pdb_order", "arguments": {"ns": "NATIVE", "subs": [""], "direction": 1}},
})
resp = recv_lumen()
result = json.loads(resp["result"]["content"][0]["text"])
print(f"ORDER first: {result['value']}")
assert result["value"] == 0.0

# 6. GET
send_lumen({
    "jsonrpc": "2.0", "id": 21, "method": "tools/call",
    "params": {"name": "pdb_get", "arguments": {"ns": "NATIVE", "subs": [0, "x"]}},
})
resp = recv_lumen()
result = json.loads(resp["result"]["content"][0]["text"])
print(f"GET: {result['value']}")
assert result["value"] == "val-0"

proc.terminate()
print("NATIVE TEST: ALL PASSED")
