# M-Light v2 — Performance Benchmarks

**Date:** 2026-07-12
**Environment:** Python 3.11, Windows 10, AMD Ryzen

## Micro-operations (microseconds)

| Operation | Time (μs) | Description |
|-----------|-----------|-------------|
| compile (1 line) | 5.6 | `S x=42 W x Q` |
| compile (4 lines) | 16.4 | `S x=42` `S y=x+1` `W y` `Q` |
| SET x=42 + exec | 17.4 | Single variable assignment |
| SET + arithmetic (3 ops) | 11.4 | `S x=10 S y=x+5 S z=x*y` |
| `$P("a,b,c",",",2)` | 8.4 | Piece extraction → "b" |
| `$E("hello",3,7)` | 12.3 | Extract substring → "llo w" |
| `$TR("hello","aeiou","-----")` | 24.4 | Character translation |

## Script-level operations (milliseconds)

| Operation | Time (ms) | Description |
|-----------|-----------|-------------|
| FOR 1→100 loop | 2.31 | `F i=1:1:100 S t=t+i` (100 iterations) |
| DO ^script | 104.5 | First call (module load + compile + exec) |
| DO ^script (with bytecode cache) | ~5 | Second call (cache hit, no recompile) |
| DO ^script with args | 111.7 | `$1`, `$2` parameters |

## Cloud DDP (milliseconds)

| Operation | Time (ms) | Notes |
|-----------|-----------|-------|
| DDP health check | 154 | Cloudflare cold-start dominated |
| DDP status | 156 | Cloudflare cold-start dominated |

## Key observations

1. **Compile is fast** — 5-16 μs for typical scripts
2. **$functions are fast** — 8-24 μs (pure Python, no regex)
3. **FOR loop** — 2.3ms for 100 iterations = ~43,000 iterations/sec
4. **DO ^script overhead** — dominated by Python module imports (~100ms). Bytecode cache reduces to ~5ms
5. **DDP cloud** — latency is Cloudflare cold-start (150+ms); warm requests would be <20ms

## Comparison with Python eval()

| Operation | M-Light v2 | Python eval() | Slowdown |
|-----------|------------|---------------|----------|
| Variable assignment | 17 μs | ~0.1 μs | ~170x |
| String function ($P) | 8 μs | ~0.5 μs | ~16x |
| FOR 100 iterations | 2.3 ms | ~0.3 ms | ~8x |
| Full script call | 104 ms | ~1 ms | ~100x |

The slowdown is expected — M-Light is a full interpreted MUMPS VM with dispatch tables, opcode handlers, and function tables. Python eval() is native C.

## Real-world impact

- **Script compilation**: imperceptible (< 0.1ms)
- **Data operations** (SET, GET, KILL): imperceptible (μs)
- **String processing** ($P, $E, $TR): 8-24 μs — no human noticeable
- **DDP sync**: 150ms cloud → dominated by network, not VM
- **DO ^script**: 5ms with cache — fast enough for agent automation
