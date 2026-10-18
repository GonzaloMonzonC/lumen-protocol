#!/usr/bin/env python3
"""Valida la clave DDP que pusimos en hub.conf contra el hub REAL (:8081).
NO imprime claves: solo huellas. Prueba /ddp/health y /ddp/pull firmados."""
import hashlib, hmac, json, re, time, urllib.request
from pathlib import Path

# 1) la clave que pusimos en hub.conf
conf = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/hub.conf")
k_conf = re.search(r"^DDP_KEY=(.+)$", conf.read_text(encoding="utf-8"), re.M).group(1).strip()

# 2) la clave "autoritativa" (poli_config.json / entorno), como hace f2c_hub_time.py
k_oficial = None
cfg = Path.home() / "AppData" / "Local" / "hermes" / "poli_config.json"
if cfg.exists():
    k_oficial = (json.loads(cfg.read_text(encoding="utf-8")) or {}).get("ddp_hmac_key")
    print(f"poli_config.json encontrado; ddp_hmac_key {'SI' if k_oficial else 'NO'}")
else:
    print("poli_config.json NO existe")

fp = lambda k: f"{k[:6]}...{k[-4:]} (sha256[:8]={hashlib.sha256(k.encode()).hexdigest()[:8]})" if k else "(vacia)"
print(f"  clave en hub.conf : {fp(k_conf)}")
print(f"  clave en poli_conf: {fp(k_oficial)}")
if k_oficial:
    print(f"  ¿COINCIDEN? {'SI ✓' if k_oficial == k_conf else 'NO 🔴'}")

# 3) prueba REAL contra el hub
def get(path, key):
    ts = str(int(time.time()))
    sig = hmac.new(key.encode(), (ts + path + key).encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request("http://127.0.0.1:8081" + path,
                                 headers={"X-DDP-Timestamp": ts, "X-DDP-HMAC": sig})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "replace")[:220]

print("\n--- prueba FIRMADA con la clave de hub.conf ---")
for path in ("/ddp/health", "/ddp/pull?ns=KANBAN&limit=3&depth=0"):
    try:
        st, body = get(path, k_conf)
        print(f"  {path}\n     -> {st}  {body}")
    except Exception as e:
        print(f"  {path}\n     -> {type(e).__name__}: {e}")

print("\n--- control: SIN firma (debe rechazar) ---")
try:
    r = urllib.request.urlopen("http://127.0.0.1:8081/ddp/pull?ns=KANBAN&limit=3", timeout=10)
    print(f"  -> {r.status} {r.read()[:160]}")
except Exception as e:
    print(f"  -> {type(e).__name__}: {e}")
