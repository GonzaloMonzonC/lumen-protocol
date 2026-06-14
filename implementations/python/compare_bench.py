"""Compare Python vs TypeScript benchmark results."""
import json, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

with open("bench_results.json", "r", encoding="utf-8") as f:
    py = json.load(f)
with open("../typescript/bench_results_expanded.json", "r", encoding="utf-8-sig") as f:
    ts = json.load(f)

py_by_name = {r["name"]: r for r in py["results"]}
ts_by_name = {r["name"]: r for r in ts["results"]}

print(f"Python:     {len(py['results'])} results")
print(f"TypeScript: {len(ts['results'])} results")
print()

cats = [
    "assembler", "compression", "hyb128_encode", "hyb128_decode", "dict",
    "json_encode", "lumen_encode", "json_decode", "lumen_decode",
    "json_roundtrip", "lumen_roundtrip", "framing_cl", "framing_hyb128",
]

print(f"{'Category':25s} {'Python ops/s':>14s} {'TS ops/s':>14s} {'Winner':>8s} {'Ratio':>6s}")
print("-" * 75)

for cat in cats:
    py_items = [r for r in py["results"] if r["category"] == cat]
    ts_items = [r for r in ts["results"] if r["category"] == cat]
    if not py_items or not ts_items:
        continue

    py_avg = sum(r["opsPerSec"] for r in py_items) / len(py_items)
    ts_avg = sum(r["opsPerSec"] for r in ts_items) / len(ts_items)
    ratio = ts_avg / py_avg if py_avg > 0 else float("inf")
    faster = "TS" if ratio > 1 else "Python"
    r = max(ratio, 1 / ratio)
    print(f"{cat:25s} {py_avg:>14,.0f} {ts_avg:>14,.0f} {faster:>8s} {r:>5.1f}x")

# Also show some individual highlights
print()
print("=== Highlights ===")
print()

# Dict lookup
pn = py_by_name.get("dict_lookup O(1)")
tn = ts_by_name.get("dict_lookup O(1)")
if pn and tn:
    print(f"Dict 1M lookups:  Python {pn['durationMs']:.1f}ms  TS {tn['durationMs']:.1f}ms")

# Compression ratio
for e in ["initialize", "tools_list", "llm_request", "error_response", "big_result"]:
    pn = py_by_name.get(f"Compress {e}")
    tn = ts_by_name.get(f"Compress {e}")
    if pn and tn:
        print(f"Compress {e:20s}: Python ratio {pn['extra']['ratioPercent']}%  TS ratio {tn['extra']['ratioPercent']}%  saved {pn['extra']['savedBytes']}B")

# Roundtrip speedup
for e in ["initialize", "tools_list", "llm_request", "error_response", "big_result"]:
    pn = py_by_name.get(f"Roundtrip LUMEN {e}")
    tn = ts_by_name.get(f"Roundtrip LUMEN {e}")
    if pn and tn:
        ps = pn["extra"].get("speedupVsJson", 0)
        ts_s = tn["extra"].get("speedupVsJson", 0)
        print(f"LUMEN vs JSON rt {e:16s}: Python {ps}x speedup  TS {ts_s}x speedup")
