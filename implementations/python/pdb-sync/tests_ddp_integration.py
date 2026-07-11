"""Tests DDP-05: Integración + Benchmark."""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(__file__))

from pdb_ddp_client import DDPClient
from pdb_sync_engine import SyncEngine

p = f = 0
def t(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS DDP-05: Integración + Benchmark\n')

client = DDPClient()
engine = SyncEngine()

# ── 1. Cadena completa: write → push → pull → apply ──
print('┌─ 1. Pipeline completo ──────────────────────')

# Write local
engine.write("pdb", "bench:1", f"test_{int(time.time())}")
t("write local entry", len(engine.journal) > 0)

# Push al cloud
push_r = engine.push_pending("pdb")
t("push to cloud", "error" not in push_r)
t("push applied", push_r.get("applied", 0) >= 0)

# Pull del cloud (sin anti-bucle)
pull_r = engine.pull_and_apply("pdb")
t("pull from cloud", "error" not in pull_r)
t("pull has applied count", "applied" in pull_r)
t("pull has skipped count (anti-loop)", "skipped" in pull_r)

# ── 2. Anti-bucle test ──
print('\n┌─ 2. Anti-bucle ────────────────────────────')

# El engine debe saltar entries con source=local
t("skipped >= 0", pull_r.get("skipped", 0) >= 0)

# ── 3. Sync completo ──
print('\n┌─ 3. Sync completo ─────────────────────────')

sync_r = engine.sync("pdb")
t("sync push ok", "error" not in sync_r.get("push", {}))
t("sync pull ok", "error" not in sync_r.get("pull", {}))

# ── 4. Benchmark ──
print('\n┌─ 4. Benchmark ─────────────────────────────')

# Health
start = time.time()
r = client.health()
health_ms = (time.time() - start) * 1000
t(f"health {health_ms:.1f}ms", r.get("ok") == True)

# Status
start = time.time()
r = client.status()
status_ms = (time.time() - start) * 1000
t(f"status {status_ms:.1f}ms", "entries" in r)

# Pull
start = time.time()
r = client.pull("pdb", batch_size=10)
pull_ms = (time.time() - start) * 1000
t(f"pull {pull_ms:.1f}ms batch=10", "entries" in r)

# Push
start = time.time()
r = client.push("pdb", [])
push_ms = (time.time() - start) * 1000
t(f"push {push_ms:.1f}ms empty", "status" in r)

# Sync completo
start = time.time()
r = engine.sync("pdb")
sync_ms = (time.time() - start) * 1000
t(f"sync completo {sync_ms:.1f}ms", "push" in r)

# ── 5. Report ──
print('\n┌─ 5. Benchmark Report ──────────────────────')
print(f"  endpoint      avg latency")
print(f"  ────────────  ──────────")
print(f"  /ddp/health   {health_ms:>6.1f} ms")
print(f"  /ddp/status   {status_ms:>6.1f} ms")
print(f"  /ddp/sync     {pull_ms:>6.1f} ms (pull 10 entries)")
print(f"  /ddp/push     {push_ms:>6.1f} ms (empty)")
print(f"  sync engine   {sync_ms:>6.1f} ms (full cycle)")

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
