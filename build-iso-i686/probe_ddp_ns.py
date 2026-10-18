#!/usr/bin/env python3
"""Sondea el hub DDP: hay registro de nodos conectados? como son los namespaces?"""
import hashlib, hmac, json, re, time, urllib.request
from pathlib import Path

conf = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/hub.conf")
KEY = re.search(r"^DDP_KEY=(.+)$", conf.read_text(encoding="utf-8"), re.M).group(1).strip()
BASE = "http://127.0.0.1:8081"


def get(path):
    ts = str(int(time.time()))
    sig = hmac.new(KEY.encode(), (ts + path + KEY).encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(BASE + path,
                                 headers={"X-DDP-Timestamp": ts, "X-DDP-HMAC": sig})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.status, r.read().decode("utf-8", "replace")


print("=== 1) endpoints de REGISTRO de nodos ===")
for p in ("/ddp/health", "/ddp/peers", "/ddp/nodes", "/ddp/clients", "/ddp/ns",
          "/ddp/info", "/ddp/stats"):
    try:
        st, body = get(p)
        print(f"  {p:16} -> {st}  {body[:170]}")
    except Exception as e:
        print(f"  {p:16} -> {type(e).__name__}: {str(e)[:70]}")

print("\n=== 2) namespaces en la raiz (depth 0) ===")
try:
    st, body = get("/ddp/pull?ns=&limit=200&depth=0")
    j = json.loads(body)
    print(f"  total={j.get('total')} success={j.get('success')}")
    for e in j.get("entries", [])[:40]:
        print(f"    ns={e.get('ns')!r}  subs={e.get('subs')}  has_children={e.get('has_children')}")
except Exception as e:
    print("  ERROR:", type(e).__name__, str(e)[:120])

print("\n=== 3) el namespace SYS (donde vive ^SYS(\"NODO\")) ===")
try:
    st, body = get("/ddp/pull?ns=SYS&limit=50&depth=1")
    print("  ", body[:400])
except Exception as e:
    print("  ERROR:", type(e).__name__, str(e)[:120])
