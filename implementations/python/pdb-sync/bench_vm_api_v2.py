#!/usr/bin/env python3
"""Benchmark vm_api v2 — concurrentes, payload grande, profundidad."""
import json, time, sys, threading, urllib.request, urllib.error, statistics

HOST_LOCAL = "http://127.0.0.1:8081"
# HOST_EXT = "http://<internal>:8443"  # ← quitado: URL interna
HOST_EXT = None  # external tests require URL override
NS = "BENCH_VM2"

def req(method, url, data=None, timeout=30):
    t0 = time.time()
    try:
        if data:
            body = json.dumps(data).encode()
            r = urllib.request.Request(url, data=body, method=method)
            r.add_header("Content-Type", "application/json")
        else:
            r = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            out = json.loads(resp.read())
        elapsed = (time.time() - t0) * 1000
        return out, elapsed
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        return {"error": str(e)}, elapsed

# ── Tests ──

def bench_write_payloads(base_url, label):
    """Write with different payload sizes."""
    results = []
    for size, label_size in [(100, "100B"), (1024, "1KB"), (10240, "10KB")]:
        entry = {"subs": ["payload"], "value": "x" * size}
        body = {"ns": NS + "_PAYLOAD", "entries": [entry]}
        out, ms = req("POST", f"{base_url}/ddp/push", body)
        results.append({
            "label": f"{label} write {label_size}",
            "n": 1, "ms": round(ms, 2),
            "ops": round(1 / (ms/1000), 1) if ms > 0 else 0,
            "ok": "error" not in out
        })
    return results

def bench_write_batches(base_url, label):
    """Write increasing batch sizes."""
    results = []
    for n in [1000, 2000]:
        entries = []
        for i in range(n):
            entries.append({"subs": [f"batch_{i}"], "value": json.dumps({"i": i, "d": "x" * 50})})
        body = {"ns": NS + "_BATCH", "entries": entries}
        out, ms = req("POST", f"{base_url}/ddp/push", body, timeout=60)
        results.append({
            "label": f"{label} write {n} batch",
            "n": n, "ms": round(ms, 2),
            "ops": round(n / (ms/1000), 1) if ms > 0 else 0,
            "ok": "error" not in out and out.get("success")
        })
    return results

def bench_read_depth(base_url, label):
    """Read with different depths."""
    results = []
    for depth in [1, 2]:
        out, ms = req("GET", f"{base_url}/ddp/pull?ns=Eval&limit=500&depth={depth}")
        ok = "error" not in out and out.get("success")
        got = len(out.get("entries", []))
        results.append({
            "label": f"{label} pull Eval depth={depth}",
            "n": got, "ms": round(ms, 2),
            "ops": round(got / (ms/1000), 1) if ms > 0 else 0,
            "ok": ok
        })
    return results

def bench_read_large_ns(base_url, label):
    """Read from large namespaces."""
    results = []
    # CHANGES is a large namespace (398K nodes)
    for limit in [100, 500]:
        out, ms = req("GET", f"{base_url}/ddp/pull?ns=CHANGES&limit={limit}&depth=0")
        ok = "error" not in out and out.get("success")
        got = len(out.get("entries", []))
        results.append({
            "label": f"{label} pull CHANGES limit={limit}",
            "n": got, "ms": round(ms, 2),
            "ops": round(got / (ms/1000), 1) if ms > 0 else 0,
            "ok": ok
        })
    return results

def bench_concurrent(base_url, label, n_threads=10, n_requests=5):
    """Concurrent reads."""
    def worker(url, results_list):
        out, ms = req("GET", url)
        results_list.append(ms)
    
    url = f"{base_url}/ddp/pull?ns=Eval&limit=5&depth=1"
    all_times = []
    for batch in range(n_requests):
        threads = []
        batch_times = []
        t0 = time.time()
        for _ in range(n_threads):
            t = threading.Thread(target=worker, args=(url, batch_times))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        elapsed = (time.time() - t0) * 1000
        all_times.extend(batch_times)
    
    results = [{
        "label": f"{label} concurrent {n_threads}x{n_requests}",
        "n": n_threads * n_requests,
        "ms": round(statistics.mean(all_times), 2),
        "ops": round((n_threads * n_requests) / (sum(all_times)/len(all_times)/1000), 1) if all_times else 0,
        "ok": True
    }]
    return results

def bench_vm_execute(base_url, label):
    """Test /vm/execute endpoint."""
    body = {"script": "S X=1+1 W X", "args": []}
    out, ms = req("POST", f"{base_url}/vm/execute", body)
    ok = "error" not in out and out.get("ok") != False
    results = [{
        "label": f"{label} vm/execute (inline)",
        "n": 1, "ms": round(ms, 2),
        "ops": round(1 / (ms/1000), 1) if ms > 0 else 0,
        "ok": ok
    }]
    return results

def bench_raw_large(base_url, label):
    """Raw endpoint with large limits."""
    results = []
    for limit in [500, 1000]:
        out, ms = req("GET", f"{base_url}/ddp/raw?ns=CHANGES&limit={limit}")
        ok = "error" not in out and out.get("success")
        got = len(out.get("entries", []))
        results.append({
            "label": f"{label} raw CHANGES limit={limit}",
            "n": got, "ms": round(ms, 2),
            "ops": round(got / (ms/1000), 1) if ms > 0 else 0,
            "ok": ok
        })
    return results

def bench_health(base_url, label):
    out, ms = req("GET", f"{base_url}/health")
    return [{"label": f"{label} health", "n": 1, "ms": round(ms, 2),
             "ops": round(1000/ms, 1) if ms > 0 else 0, "ok": "error" not in out}]

# ── Run ──
all_results = []

for host, label in [(HOST_LOCAL, "Local"), (HOST_EXT, "Ext")]:
    all_results.extend(bench_health(host, label))
    all_results.extend(bench_write_payloads(host, label))
    all_results.extend(bench_read_depth(host, label))
    all_results.extend(bench_read_large_ns(host, label))
    all_results.extend(bench_raw_large(host, label))
    all_results.extend(bench_concurrent(host, label))

# Write batches and vm/execute only local (write changes state)
all_results.extend(bench_write_batches(HOST_LOCAL, "Local"))
all_results.extend(bench_vm_execute(HOST_LOCAL, "Local"))

# Clean up test data
req("POST", f"{HOST_LOCAL}/ddp/push", {"ns": NS + "_PAYLOAD", "entries": [{"subs": ["_cleanup"], "value": "done"}]})

# Print
print(f"{'Benchmark':<42} {'n':>6} {'ms':>8} {'ops/s':>8} {'OK':>4}")
print("-" * 70)
for r in all_results:
    ok_mark = "✅" if r["ok"] else "❌"
    print(f"{r['label']:<42} {r['n']:>6} {r['ms']:>8.1f} {r['ops']:>8.1f} {ok_mark:>4}")

ok = sum(1 for r in all_results if r["ok"])
fail = sum(1 for r in all_results if not r["ok"])
local_ms = [r["ms"] for r in all_results if "Local" in r["label"]]
ext_ms = [r["ms"] for r in all_results if "Ext" in r["label"]]

print(f"\n📊 {ok}/{len(all_results)} tests passed | {fail} failed")
print(f"⚡ Local avg: {statistics.mean(local_ms):.1f}ms  median: {statistics.median(local_ms):.1f}ms")
print(f"🌐 Ext   avg: {statistics.mean(ext_ms):.1f}ms  median: {statistics.median(ext_ms):.1f}ms")
print(f"🚀 Ratio ext/local: {statistics.mean(ext_ms)/statistics.mean(local_ms):.2f}x")

# Highlight fastest
fastest_local = min((r for r in all_results if "Local" in r["label"]), key=lambda r: r["ms"])
fastest_ext = min((r for r in all_results if "Ext" in r["label"]), key=lambda r: r["ms"])
print(f"\n⚡ Fastest local: {fastest_local['label']} → {fastest_local['ms']}ms")
print(f"⚡ Fastest ext:   {fastest_ext['label']} → {fastest_ext['ms']}ms")
