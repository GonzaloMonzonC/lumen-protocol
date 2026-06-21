#!/usr/bin/env python3
"""PDBM-Lumen 100K benchmark via SHM transport."""
import sys, os, json, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "python", "src"))

os.environ["PDB_PATH"] = "/c/tmp/shm_100k.db"

from lumen import (
    build_frame, build_size, parse_frame, compress_value, decompress_value,
    FLAG_COMPRESSED, TYPE_REQUEST, ParseComplete,
    ShmRegion, ShmTransport, RingSide,
)

import subprocess
proc = subprocess.Popen(
    [sys.executable, "-u", "server_shm.py"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=False,
)

# ── PROBE ──
probe = compress_value({"protocol": "LUMEN", "client_name": "bench", "supported_versions": ["1.0"]})
buf = bytearray(build_size(payload_len=len(probe)))
build_frame(TYPE_REQUEST, FLAG_COMPRESSED, probe, buf, 0)
proc.stdin.write(buf); proc.stdin.flush()

rb = bytearray()
for _ in range(2000):
    b = proc.stdout.read(1)
    if not b: break
    rb.extend(b)
    r = parse_frame(rb, 0)
    if isinstance(r, ParseComplete):
        ack = decompress_value(r.frame.payload) if r.frame.flags & FLAG_COMPRESSED else r.frame.payload
        break

time.sleep(0.1)
region = ShmRegion.open(ack["shm_region"], ack["shm_size"])
region.validate()
write_ring = region.ring_buffer(RingSide.A)
read_ring = region.ring_buffer(RingSide.B)
transport = ShmTransport(write_ring, read_ring)

def send_shm(data):
    payload = compress_value(data)
    buf = bytearray(build_size(payload_len=len(payload)))
    build_frame(TYPE_REQUEST, FLAG_COMPRESSED, payload, buf, 0)
    transport.send_frame(bytes(buf))

def recv_shm():
    raw = transport.recv_frame()
    if raw is None: raise TimeoutError("timeout")
    r = parse_frame(bytearray(raw), 0)
    if isinstance(r, ParseComplete):
        return decompress_value(r.frame.payload) if r.frame.flags & FLAG_COMPRESSED else r.frame.payload
    return None

# Initialize
send_shm({"jsonrpc": "2.0", "id": 1, "method": "initialize",
           "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "bench"}}})
recv_shm()

# ════════════════════════════════════════
print("=" * 60)
print("  PDBM-Lumen SHM Benchmark")
print("=" * 60)

results = []

def bench(name, fn, n):
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    t1 = time.perf_counter()
    total_ms = (t1 - t0) * 1000
    avg_us = total_ms * 1000 / n
    print(f"  {name:30s} {n:>6,} ops  {total_ms:>8.1f}ms  {avg_us:>6.1f}μs/op")
    return {"name": name, "n": n, "total_ms": total_ms, "avg_us": avg_us}

_id = [100]

def req(method, params):
    _id[0] += 1
    send_shm({"jsonrpc": "2.0", "id": _id[0], "method": "tools/call",
              "params": {"name": method, "arguments": params}})
    return recv_shm()

# 1. SET single node 100K
results.append(bench("SET (single node)", lambda: req("pdb_set", {"ns": "B", "subs": [0], "value": "x"}), 100_000))

# 2. GET exact key 100K
results.append(bench("GET (exact key)", lambda: req("pdb_get", {"ns": "B", "subs": [0]}), 100_000))

# 3. $DATA exists 100K
results.append(bench("$DATA (exists)", lambda: req("pdb_data", {"ns": "B", "subs": [0]}), 100_000))

# 4. $INCREMENT 100K
results.append(bench("$INCREMENT", lambda: req("pdb_incr", {"ns": "C", "subs": ["x"], "increment": 1}), 100_000))

# 5. SET 3-level tree
results.append(bench("SET (3-level)", lambda: req("pdb_set", {"ns": "D", "subs": [1, "name"], "value": "u"}), 100_000))

# Summary
print("-" * 60)
total_ops = sum(r["n"] for r in results)
print(f"  Total: {total_ops:,} operations")

# Save
with open("benchmark_shm.json", "w") as f:
    json.dump({"benchmark": "PDBM-Lumen SHM", "date": time.strftime("%Y-%m-%d %H:%M"), "results": results}, f, indent=2)
print(f"  Saved: benchmark_shm.json")

proc.terminate()
print("DONE")
