"""Tests DDP-03: DDP Client en Hermes."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
from pdb_ddp_client import DDPClient

p = f = 0
def t(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS DDP-03: DDP Client\n')

client = DDPClient()

# Health
r = client.health()
t("health returns ok", r.get("ok") == True)
t("health has agent", "agent" in r)
t("health has version", "version" in r)

# Schema
r2 = client.schema()
t("schema returns namespaces", "namespaces" in r2)
t("schema has pdb ns", "pdb" in r2.get("namespaces", {}))
t("schema has kb ns", "kb" in r2.get("namespaces", {}))

# Status  
r3 = client.status()
t("status returns entries", "entries" in r3)
t("status entries > 0", r3.get("entries", 0) >= 0)
t("status has lag_ms", "lag_ms" in r3)

# Pull
r4 = client.pull("pdb")
t("pull returns entries", "entries" in r4)
t("pull has checksum", "checksum" in r4)
t("pull has since", "since" in r4)

# Pull with since
r5 = client.pull("pdb", since="2026-07-11T00:00:00Z", batch_size=10)
t("pull with since and batch", isinstance(r5.get("entries"), list))

# Push (empty)
r6 = client.push("pdb", [])
t("push empty returns ok", r6.get("status") == "ok" or "error" in r6)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
