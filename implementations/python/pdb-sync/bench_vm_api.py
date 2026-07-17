#!/usr/bin/env python3
"""Benchmark vm_api: lectura/escritura local y externa."""
import json, time, sys, urllib.request, urllib.error

LOCAL = "http://127.0.0.1:8081"
EXTERNAL = "http://vm-api.cadences.app:8443"
NS = "BENCH_VM"

def req(method, url, data=None):
    t0 = time.time()
    try:
        if data:
            body = json.dumps(data).encode()
            r = urllib.request.Request(url, data=body, method=method)
            r.add_header("Content-Type", "application/json")
        else:
            r = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(r, timeout=30) as resp:
            out = json.loads(resp.read())
        elapsed = (time.time() - t0) * 1000
        return out, elapsed
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        return {"error": str(e)}, elapsed

def bench_write(label, base_url, n_entries):
    entries = []
    for i in range(n_entries):
        entries.append({
            "subs": [f"bench_{i}"],
            "value": json.dumps({
                "id": i,
                "name": f"test-{i}",
                "data": "x" * 100,
                "ts": time.time()
            })
        })
    body = {"ns": NS + "_WRITE", "entries": entries}
    out, ms = req("POST", f"{base_url}/ddp/push", body)
    ok = "error" not in out and out.get("success")
    return {
        "label": f"{label} write {n_entries}",
        "n": n_entries,
        "ms": round(ms, 2),
        "ops": round(n_entries / (ms/1000), 1) if ms > 0 else 0,
        "ok": ok
    }

def bench_read(base_url, label, ns, limit):
    out, ms = req("GET", f"{base_url}/ddp/pull?ns={ns}&limit={limit}&depth=1")
    ok = "error" not in out and out.get("success")
    got = len(out.get("entries", []))
    return {
        "label": f"{label} read {ns} limit={limit}",
        "n": got,
        "ms": round(ms, 2),
        "ops": round(got / (ms/1000), 1) if ms > 0 else 0,
        "ok": ok
    }

def bench_raw(base_url, label, ns, limit):
    out, ms = req("GET", f"{base_url}/ddp/raw?ns={ns}&limit={limit}")
    ok = "error" not in out and out.get("success")
    got = len(out.get("entries", []))
    return {
        "label": f"{label} raw {ns} limit={limit}",
        "n": got,
        "ms": round(ms, 2),
        "ops": round(got / (ms/1000), 1) if ms > 0 else 0,
        "ok": ok
    }

def bench_namespaces(base_url, label):
    out, ms = req("GET", f"{base_url}/ddp/namespaces")
    ok = "error" not in out and out.get("success")
    got = len(out.get("namespaces", []))
    return {
        "label": f"{label} namespaces",
        "n": got,
        "ms": round(ms, 2),
        "ops": round(got / (ms/1000), 1) if ms > 0 else 0,
        "ok": ok
    }

def bench_health(base_url, label):
    out, ms = req("GET", f"{base_url}/health")
    ok = "error" not in out
    return {
        "label": f"{label} health",
        "n": 1,
        "ms": round(ms, 2),
        "ops": round(1000 / ms, 1) if ms > 0 else 0,
        "ok": ok
    }

results = []

# 1. Health
for url, label in [(LOCAL, "Local"), (EXTERNAL, "Ext")]:
    results.append(bench_health(url, label))

# 2. Namespaces
for url, label in [(LOCAL, "Local"), (EXTERNAL, "Ext")]:
    results.append(bench_namespaces(url, label))

# 3. Write benchmarks (local only - writes change state)
for n in [1, 10, 100, 500]:
    results.append(bench_write("Local", LOCAL, n))

# 4. Read benchmarks - pull Eval
for limit in [10, 100, 500]:
    results.append(bench_read(LOCAL, "Local", "Eval", limit))
    results.append(bench_read(EXTERNAL, "Ext", "Eval", limit))

# 5. Read benchmarks - pull clinica (raw data, depth=0)
for limit in [10, 100]:
    results.append(bench_read(LOCAL, "Local", "clinica", limit))
    results.append(bench_read(EXTERNAL, "Ext", "clinica", limit))

# 6. Raw endpoint
for limit in [10, 100]:
    results.append(bench_raw(LOCAL, "Local", "clinica", limit))
    results.append(bench_raw(EXTERNAL, "Ext", "clinica", limit))

# Print results table
print(f"{'Benchmark':<40} {'n':>6} {'ms':>8} {'ops/s':>8} {'OK':>4}")
print("-" * 68)
for r in results:
    ok_mark = "✅" if r["ok"] else "❌"
    print(f"{r['label']:<40} {r['n']:>6} {r['ms']:>8.1f} {r['ops']:>8.1f} {ok_mark:>4}")

# Summary
ok_count = sum(1 for r in results if r["ok"])
fail_count = sum(1 for r in results if not r["ok"])
avg_ms_local = sum(r["ms"] for r in results if "Local" in r["label"]) / max(1, sum(1 for r in results if "Local" in r["label"]))
avg_ms_ext = sum(r["ms"] for r in results if "Ext" in r["label"]) / max(1, sum(1 for r in results if "Ext" in r["label"]))
print(f"\n📊 {ok_count}/{len(results)} tests passed | {fail_count} failed")
print(f"⚡ Local avg: {avg_ms_local:.1f}ms  |  Ext avg: {avg_ms_ext:.1f}ms")
print(f"🚀 Ratio ext/local: {avg_ms_ext/avg_ms_local:.1f}x")
