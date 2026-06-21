#!/usr/bin/env python3
"""SHM debug — test server_shm.py via LUMEN stdio transport."""
import sys, os, json, subprocess, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "python", "src"))

os.environ["PDB_PATH"] = "/c/tmp/shm_debug.db"

from lumen import (
    build_frame, build_size, parse_frame, compress_value, decompress_value,
    FLAG_COMPRESSED, TYPE_REQUEST, ParseComplete,
    ShmRegion, ShmTransport, RingSide,
)

proc = subprocess.Popen(
    [sys.executable, "-u", "server_shm.py"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=False,
)

# ── PROBE handshake via stdio ──
probe = compress_value({"protocol": "LUMEN", "client_name": "test", "supported_versions": ["1.0"]})
buf = bytearray(build_size(payload_len=len(probe)))
build_frame(TYPE_REQUEST, FLAG_COMPRESSED, probe, buf, 0)
proc.stdin.write(buf)
proc.stdin.flush()

rb = bytearray()
ack = None
for _ in range(2000):
    b = proc.stdout.read(1)
    if not b: break
    rb.extend(b)
    r = parse_frame(rb, 0)
    if isinstance(r, ParseComplete):
        pl = decompress_value(r.frame.payload) if r.frame.flags & FLAG_COMPRESSED else r.frame.payload
        ack = pl
        break

if not ack:
    print("NO ACK")
    print("STDERR:", proc.stderr.read().decode()[:1000])
    proc.terminate()
    exit(1)

shm_name = ack.get("shm_region")
shm_size = ack.get("shm_size")
print(f"ACK: server={ack.get('server_name')}, shm={shm_name}, size={shm_size}")

if not shm_name:
    print("NO SHM in ACK")
    proc.terminate()
    exit(1)

# ── Open SHM region ──
time.sleep(0.1)  # extra delay for Windows
print("Opening SHM region...")
try:
    region = ShmRegion.open(shm_name, shm_size)
    if not region.validate():
        print("SHM VALIDATION FAILED")
        proc.terminate()
        exit(1)
    print("SHM region valid")
except Exception as e:
    print(f"SHM OPEN ERROR: {e}")
    print("STDERR:", proc.stderr.read().decode()[:1000])
    proc.terminate()
    exit(1)

# Client: write to Ring A, read from Ring B
write_ring = region.ring_buffer(RingSide.A)
read_ring = region.ring_buffer(RingSide.B)
transport = ShmTransport(write_ring, read_ring)
print("SHM transport ready")

# ── Send initialize via SHM ──
def send_shm(data):
    payload = compress_value(data)
    buf = bytearray(build_size(payload_len=len(payload)))
    build_frame(TYPE_REQUEST, FLAG_COMPRESSED, payload, buf, 0)
    transport.send_frame(bytes(buf))

def recv_shm(timeout=True):
    raw = transport.recv_frame()
    if raw is None:
        if not timeout:
            return None
        raise TimeoutError("SHM recv timeout")
    r = parse_frame(bytearray(raw), 0)
    if isinstance(r, ParseComplete):
        return decompress_value(r.frame.payload) if r.frame.flags & FLAG_COMPRESSED else r.frame.payload
    return None

# Initialize
send_shm({"jsonrpc": "2.0", "id": 1, "method": "initialize",
           "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                      "clientInfo": {"name": "test"}}})
resp = recv_shm()
print(f"INIT: {resp['result']['serverInfo']['name']}")

# tools/list
send_shm({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
resp = recv_shm()
tools = [t["name"] for t in resp["result"]["tools"]]
print(f"TOOLS: {len(tools)} — {', '.join(tools[:5])}...")

# ── BENCHMARK 100K via SHM ──
print("\nBenchmark 100K operations via SHM...")

t0 = time.perf_counter()
for i in range(1000):
    send_shm({"jsonrpc": "2.0", "id": 100+i, "method": "tools/call",
              "params": {"name": "pdb_set", "arguments": {"ns": "SHM_BENCH", "subs": [i, "name"], "value": f"user-{i}"}}})
    resp = recv_shm()
t1 = time.perf_counter()
print(f"  1000 SET (3-level): {(t1-t0)*1000:.1f}ms ({((t1-t0)/1000)*1e6:.0f}μs per op)")

t0 = time.perf_counter()
for i in range(1000):
    send_shm({"jsonrpc": "2.0", "id": 200+i, "method": "tools/call",
              "params": {"name": "pdb_get", "arguments": {"ns": "SHM_BENCH", "subs": [i, "name"]}}})
    resp = recv_shm()
t1 = time.perf_counter()
print(f"  1000 GET: {(t1-t0)*1000:.1f}ms ({((t1-t0)/1000)*1e6:.0f}μs per op)")

proc.terminate()
print("\nSHM BENCHMARK DONE")
