#!/usr/bin/env python3
"""Benchmark suite: Poli MVM vs Python nativo vs referencia."""
import json, subprocess, sys, time, math, statistics

# ── Helpers ──
GREEN = "✅"
YELLOW = "⚡"
BLUE = "🔵"
RED = "❌"

def banner(s):
    print(f"\n{'═'*60}")
    print(f"  {s}")
    print(f"{'═'*60}")

class PoliBench:
    def __init__(self):
        self.srv = subprocess.Popen(
            [sys.executable, 'poli_server.py'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
    def rpc(self, name, args=None):
        msg = {'jsonrpc': '2.0', 'id': 1, 'method': name}
        if args: msg['params'] = args
        self.srv.stdin.write(json.dumps(msg) + '\n'); self.srv.stdin.flush()
        return json.loads(self.srv.stdout.readline())
    def call(self, name, args):
        r = self.rpc('tools/call', {'name': name, 'arguments': args})
        return json.loads(r['result']['content'][0]['text'])
    def close(self):
        self.srv.terminate(); self.srv.wait()

def bench(label, fn, iterations=5, warmup=1):
    """Ejecuta fn() con warmup + iterations, devuelve (ok, times, mean, std, median)."""
    for _ in range(warmup):
        try: fn()
        except: pass
    times = []
    for i in range(iterations):
        t0 = time.perf_counter()
        try:
            result = fn()
            elapsed = time.perf_counter() - t0
            times.append(elapsed)
        except Exception as e:
            print(f"  {RED} #{i} {label}: {e}")
            times.append(None)
    times = [t for t in times if t is not None]
    if not times:
        return False, [], 0, 0, 0
    mean = statistics.mean(times)
    std = statistics.stdev(times) if len(times) > 1 else 0
    median = statistics.median(times)
    return True, times, mean, std, median

def fmt_time(seconds):
    if seconds < 1:
        return f"{seconds*1000:.1f}ms"
    return f"{seconds:.2f}s"

def fmt_stats(mean, std, median):
    return f"{fmt_time(mean)} ± {fmt_time(std)} (med: {fmt_time(median)})"

# ═══════════════════════════════════════
# BENCHMARKS
# ═══════════════════════════════════════

def run_benchmarks():
    poli = PoliBench()
    poli.rpc('initialize')
    poli.call('poli_seed', {})
    
    results = {}
    
    # ── 1. RAW M EXECUTION ──
    banner("1. 📐 RAW M EXECUTION")
    
    def m_empty():
        return poli.call('poli_exec', {'source': 'S x=1', 'gas_limit': 10000})
    ok, times, m, s, md = bench("M: SET x=1", m_empty, iterations=10)
    results['M SET'] = (ok, m, s, md)
    
    def m_loop():
        return poli.call('poli_exec', {'source': 'F i=1:1:1000 S x=x+i', 'gas_limit': 500000})
    ok, times, m, s, md = bench("M: loop 1..1000", m_loop, iterations=5)
    results['M loop 1k'] = (ok, m, s, md)
    
    def m_math():
        return poli.call('poli_exec', {'source': 'S x=42*3.14159/2+100', 'gas_limit': 10000})
    ok, times, m, s, md = bench("M: math ops", m_math, iterations=10)
    results['M math'] = (ok, m, s, md)
    
    # ── 2. HTTP THROUGHPUT ──
    banner("2. 🌐 HTTP THROUGHPUT")
    
    def http_get():
        return poli.call('poli_http', {'method': 'get', 'url': 'https://httpbin.org/uuid'})
    ok, times, m, s, md = bench("HTTP GET /uuid", http_get, iterations=5)
    results['HTTP GET'] = (ok, m, s, md)
    
    def http_post():
        return poli.call('poli_http', {'method': 'post', 'url': 'https://httpbin.org/post', 'body': '{"bench":"test"}'})
    ok, times, m, s, md = bench("HTTP POST /post", http_post, iterations=5)
    results['HTTP POST'] = (ok, m, s, md)
    
    # ── 3. LLM LATENCY ──
    banner("3. 🤖 LLM LATENCY")
    
    def llm_simple():
        return poli.call('poli_llm', {'prompt': 'responde solo OK'})
    ok, times, m, s, md = bench("LLM: simple", llm_simple, iterations=3)
    results['LLM simple'] = (ok, m, s, md)
    
    # ── 4. FIBER OVERHEAD ──
    banner("4. 🧵 FIBER OVERHEAD")
    
    def fiber_spawn():
        return poli.call('poli_fiber', {'action': 'spawn', 'source': 'S x=1 S ^R=x'})
    ok, times, m, s, md = bench("Fiber spawn", fiber_spawn, iterations=10)
    results['Fiber spawn'] = (ok, m, s, md)
    
    def fiber_spawn_join():
        r = poli.call('poli_fiber', {'action': 'spawn', 'source': 'S x=1 S ^R=x'})
        fid = r.get('fiber_id')
        if fid:
            return poli.call('poli_fiber', {'action': 'join', 'fiber_id': fid})
        return {'ok': False}
    ok, times, m, s, md = bench("Fiber spawn+join", fiber_spawn_join, iterations=10)
    results['Fiber spawn+join'] = (ok, m, s, md)
    
    # ── 5. THROUGHPUT (calls/sec) ──
    banner("5. ⚡ THROUGHPUT (calls/sec)")
    
    def burst(n=10):
        t0 = time.time()
        for _ in range(n):
            poli.call('poli_exec', {'source': 'S x=1', 'gas_limit': 10000})
        elapsed = time.time() - t0
        return n / elapsed
    # Warmup
    burst(3)
    calls_sec = burst(20)
    results['Throughput'] = (True, 1/calls_sec, 0, 0)  # Store as time-per-call
    
    # ── 6. PYTHON BASELINE ──
    banner("6. 🐍 PYTHON BASELINE (mismas operaciones)")
    
    def py_empty():
        x = 1
    ok, times, m, s, md = bench("Python: x=1", py_empty, iterations=1000)
    results['Py SET'] = (ok, m*1_000_000, s*1_000_000, md*1_000_000)  # convert to microsec
    
    def py_loop():
        x = 0
        for i in range(1000):
            x += i
    ok, times, m, s, md = bench("Python: loop 1k", py_loop, iterations=100)
    results['Py loop 1k'] = (ok, m, s, md)
    
    def py_math():
        x = 42 * 3.14159 / 2 + 100
    ok, times, m, s, md = bench("Python: math", py_math, iterations=1000)
    results['Py math'] = (ok, m*1_000_000, s*1_000_000, md*1_000_000)
    
    def py_http():
        import urllib.request
        with urllib.request.urlopen('https://httpbin.org/uuid', timeout=5):
            pass
    ok, times, m, s, md = bench("Python: HTTP GET", py_http, iterations=5)
    results['Py HTTP GET'] = (ok, m, s, md)
    
    poli.close()
    return results

# ═══════════════════════════════════════
# REPORT
# ═══════════════════════════════════════

def print_results(results):
    banner("📊 COMPARATIVA: Poli MVM vs Python")
    
    # Categorías
    cats = {
        "Operaciones básicas": ["M SET", "M math", "M loop 1k", "Py SET", "Py math", "Py loop 1k"],
        "HTTP": ["HTTP GET", "HTTP POST", "Py HTTP GET"],
        "LLM": ["LLM simple"],
        "Fibers": ["Fiber spawn", "Fiber spawn+join"],
        "Throughput": ["Throughput"],
    }
    
    for cat, keys in cats.items():
        print(f"\n  ┌─ {cat} {'─'*40}")
        print(f"  │ {'Medición':30s} {'Poli MVM':>12s} {'Python':>12s} {'Ratio':>8s}")
        print(f"  │ {'─'*62}")
        
        for key in keys:
            if key not in results:
                continue
            r = results[key]
            ok, val, std, med = r if len(r) == 4 else (r[0], r[1], 0, 0)
            if not ok:
                print(f"  │ {key:30s} {'❌':>12s} {'':>12s} {'':>8s}")
                continue
            
            # Find Python counterpart
            py_key = f"Py {key}" if not key.startswith("Py") else None
            if py_key and py_key in results:
                pr = results[py_key]
                pok, pv, ps, pm = pr if len(pr) == 4 else (pr[0], pr[1], 0, 0)
                if pok and pv > 0:
                    ratio = val / pv
                    unit = "µs" if key in ("M SET", "M math") else "s"
                    p_unit = "µs" if py_key in ("Py SET", "Py math") else "s"
                    print(f"  │ {key:30s} {fmt_time(val):>12s} {fmt_time(pv):>12s} {ratio:>7.1f}x")
                else:
                    print(f"  │ {key:30s} {fmt_time(val):>12s} {'❌':>12s} {'':>8s}")
            elif key == "Throughput":
                calls_per_sec = 1.0 / val if val > 0 else 0
                print(f"  │ {'Calls/sec':30s} {calls_per_sec:>10.0f}/s{'':>12s}")
            else:
                print(f"  │ {key:30s} {fmt_time(val):>12s}")

    # ═══ Scoreboard ═══
    banner("🏆 SCOREBOARD")
    scores = []
    
    def score(val, py_key, results):
        if py_key in results and results[py_key][0]:
            pv = results[py_key][1]
            if pv > 0:
                return val / pv  # Higher = faster relative to Python
        return None
    
    for key in ["M SET", "M math", "M loop 1k"]:
        if key in results and results[key][0]:
            r = results[key]
            v = r[1]  # mean
            s = score(v, f"Py {key}", results)
            if s:
                scores.append((key, v, s))
    
    print(f"  {'Benchmark':30s} {'MVM':>10s} {'vs Python':>10s}")
    print(f"  {'─'*50}")
    for name, val, ratio in scores:
        unit = "µs" if name in ("M SET", "M math") else "ms" if val < 1 else "s"
        val_str = f"{val*1_000_000 if unit == 'µs' else val*1000 if unit == 'ms' else val:.1f}{unit}"
        print(f"  {name:30s} {val_str:>10s} {ratio:>8.1f}x {'🐢' if ratio > 100 else '🐇' if ratio < 1 else '🔶'}")

    # ═══ Verdict ═══
    banner("📋 VEREDICTO")
    
    mvm_ops = any(results.get(k, [False])[0] for k in ["M loop 1k", "M SET"])
    llm_ok = results.get("LLM simple", [False])[0]
    fiber_ok = results.get("Fiber spawn+join", [False])[0]
    http_ok = results.get("HTTP GET", [False])[0]
    
    total = sum(1 for k, v in results.items() if v[0])
    total_all = len(results)
    print(f"  Benchmarks completados: {total}/{total_all}")
    print(f"  MVM funcional:    {'✅' if mvm_ops else '❌'} Operaciones M")
    print(f"  LLM pipeline:     {'✅' if llm_ok else '❌'} LLM nativo Rust")
    print(f"  Fiber system:     {'✅' if fiber_ok else '❌'} Thread workers")
    print(f"  HTTP client:      {'✅' if http_ok else '❌'} minreq nativo")
    
    if total == total_all:
        print(f"\n  🏆 SISTEMA COMPLETO — todos los benchmarks pasaron")
    
    # Recomendaciones
    print(f"\n  💡 Recomendaciones:")
    slow_ops = [(k, v[1]) for k, v in results.items() if v[0] and v[1] > 0.5 and not k.startswith("Py") and k != "Throughput"]
    if slow_ops:
        print(f"     Operaciones lentas (>500ms): {', '.join(k for k, _ in slow_ops)}")
    if mvm_ops and results.get("M loop 1k", [False, 0])[1] > 0.01:
        ratio = results["M loop 1k"][1] / results.get("Py loop 1k", [True, 0.001])[1]
        print(f"     MVM loop overhead: ~{ratio:.0f}x vs Python (esperado para lenguaje interpretado)")

if __name__ == '__main__':
    print(f"{'═'*60}")
    print(f"  POLI MVM — BENCHMARK SUITE COMPLETA")
    print(f"  Fecha: {time.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'═'*60}")
    
    results = run_benchmarks()
    print_results(results)
