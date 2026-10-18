#!/usr/bin/env python3
"""El hub guarda los VALORES de NODO? Consulta cruda /ddp/raw (SQL directo)."""
import hashlib, hmac, json, re, time, urllib.request, urllib.error
from pathlib import Path

KEY = re.search(r"^DDP_KEY=(.+)$",
                Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/hub.conf")
                .read_text(encoding="utf-8"), re.M).group(1).strip()


def get(path):
    ts = str(int(time.time()))
    sig = hmac.new(KEY.encode(), (ts + path + KEY).encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request("http://127.0.0.1:8081" + path,
                                 headers={"X-DDP-Timestamp": ts, "X-DDP-HMAC": sig})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"http": e.code, "body": e.read().decode()[:200]}
    except Exception as e:
        return {"err": str(e)}


print("=== /ddp/raw?ns=NODO (SQL directo, valores reales) ===")
d = get("/ddp/raw?ns=NODO&limit=40")
if isinstance(d, dict):
    it = d.get("entries") or d.get("rows") or []
    print(f"  claves: {list(d.keys())}   filas: {len(it)}")
    for e in it[:14]:
        print(f"    {json.dumps(e, ensure_ascii=False)[:150]}")
else:
    print("  ", d)

print("\n=== /ddp/raw?ns=NODOS (control: este SI tenia valores) ===")
d = get("/ddp/raw?ns=NODOS&limit=10")
it = d.get("entries") or d.get("rows") or [] if isinstance(d, dict) else []
print(f"  filas: {len(it)}")
for e in it[:6]:
    print(f"    {json.dumps(e, ensure_ascii=False)[:150]}")
