"""Full sync: push todos los datos locales existentes al edge."""
import sys, os, json, time

sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync"))

from pdb_tools import tool_order, tool_get
from pdb_journal import make_entry, write, read
from pdb_ddp_client import DDPClient

client = DDPClient()

# 1. Namespaces a sincronizar (CHANGES es WAL interno, no replica)
namespaces = ['System', 'ROUTINE', 'Agent', 'TEST']
print(f"Namespaces a sincronizar: {namespaces}")

# 2. Para cada namespace, recorrer entries y crear WAL
total = 0
for ns in namespaces:
    key = ""
    count = 0
    while True:
        r = tool_order({"ns": ns, "subs": [key], "direction": 1})
        if not r.get("success") or not r.get("value"):
            break
        key = r["value"]
        val_r = tool_get({"ns": ns, "subs": [key]})
        val = val_r.get("value", "") if val_r.get("success") else ""
        # Crear WAL entry
        entry = make_entry(ns, key, str(val)[:500], source="local")
        write(entry)
        count += 1
        total += 1
    if count > 0:
        print(f"  ^{ns}: {count} entries → WAL")

print(f"\n📦 Total WAL entries creadas: {total}")

# 3. Push al edge
if total > 0:
    print("\nPusheando al edge...")
    wal = read(source="local", limit=500)
    batch = []
    for e in wal:
        batch.append({
            "key": e["key"].encode().hex(),
            "value": json.dumps(e),
            "source": "local",
            "updated_at": e["ts"],
        })
        if len(batch) >= 50:
            r = client.push("pdb", batch)
            print(f"  Push 50 entries: {r.get('applied', 0)} applied")
            batch = []
    
    if batch:
        r = client.push("pdb", batch)
        print(f"  Push {len(batch)} entries: {r.get('applied', 0)} applied")

# 4. Verificar
status = client.status()
print(f"\n✅ Edge ahora tiene {status.get('entries', '?')} entries")
print(f"📊 Sincronización completada")
