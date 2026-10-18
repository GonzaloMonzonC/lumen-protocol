import hashlib, hmac, json, re, time, urllib.request
from pathlib import Path
KEY = re.search(r"^DDP_KEY=(.+)$", Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/hub.conf").read_text(encoding="utf-8"), re.M).group(1).strip()
p = "/ddp/pull?ns=SYS&limit=2&depth=1"
ts = str(int(time.time()))
sig = hmac.new(KEY.encode(), (ts + p + KEY).encode(), hashlib.sha256).hexdigest()
r = urllib.request.Request("http://127.0.0.1:8081" + p, headers={"X-DDP-Timestamp": ts, "X-DDP-HMAC": sig})
d = json.loads(urllib.request.urlopen(r, timeout=15).read())
print("claves:", list(d.keys()))
e = (d.get("entries") or [{}])[0]
print("entrada[0]:", json.dumps(e, ensure_ascii=False)[:300])
