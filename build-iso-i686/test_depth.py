#!/usr/bin/env python3
"""Que 'depth' hace falta para que el pull traiga los VALORES?"""
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
        return {"http": e.code}
    except Exception as e:
        return {"err": str(e)}


print(f"{'depth':<7} {'entradas':<9} {'con valor':<10} ejemplo")
print("-" * 78)
for dp in (0, 1, 2, 3, 5, -1):
    d = get(f"/ddp/pull?ns=NODO&limit=200&depth={dp}")
    ents = d.get("entries", []) if isinstance(d, dict) else []
    con = [e for e in ents if e.get("value")]
    ej = json.dumps(con[0]["subs"], ensure_ascii=False) + " = " + str(con[0]["value"])[:28] if con else "-"
    print(f"{dp:<7} {len(ents):<9} {len(con):<10} {ej}")

print("\n=== y con prefix=el id del nodo? ===")
for dp in (2, 3, -1):
    d = get(f"/ddp/pull?ns=NODO&limit=200&depth={dp}&prefix=Asus-1005HA")
    ents = d.get("entries", []) if isinstance(d, dict) else []
    con = [e for e in ents if e.get("value")]
    print(f"  depth={dp}: {len(ents)} entradas, {len(con)} con valor")
    for e in con[:4]:
        print(f"     {e['subs']} = {str(e['value'])[:36]}")
