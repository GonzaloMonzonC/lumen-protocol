#!/usr/bin/env python3
"""VERIFICACION END-TO-END de la opcion B contra el hub VIVO (:8081)."""
import hashlib, hmac, re, time, urllib.request, urllib.error
from pathlib import Path

KEY = re.search(r"^DDP_KEY=(.+)$",
                Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/hub.conf")
                .read_text(encoding="utf-8"), re.M).group(1).strip()
print(f"clave leida de hub.conf (len={len(KEY)})")

BASE = "http://127.0.0.1:8081"
PATH = "/ddp/pull?ns=SYS&limit=1"
NODO = "QEMU-Standard-PC"


def pide(hdrs):
    req = urllib.request.Request(BASE + PATH, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return f"ERR {e}"


ts = str(int(time.time()))
legacy = hmac.new(KEY.encode(), (ts + PATH + KEY).encode(), hashlib.sha256).hexdigest()
hmac2 = hmac.new(KEY.encode(), (ts + NODO + PATH + KEY).encode(), hashlib.sha256).hexdigest()
hmac2_otro = hmac.new(KEY.encode(), (ts + "Otro-Nodo" + PATH + KEY).encode(),
                      hashlib.sha256).hexdigest()

casos = [
    ("1) legacy (nodo actual)", {"X-DDP-Timestamp": ts, "X-DDP-HMAC": legacy}, 200),
    ("2) identidad correcta", {"X-DDP-Timestamp": ts, "X-DDP-Node": NODO,
                               "X-DDP-HMAC2": hmac2, "X-DDP-HMAC": legacy}, 200),
    ("3) dice ser OTRO nodo (firma del primero)",
     {"X-DDP-Timestamp": ts, "X-DDP-Node": "Otro-Nodo",
      "X-DDP-HMAC2": hmac2, "X-DDP-HMAC": legacy}, 403),
    ("3b) reclama otro nombre CON su firma (tiene la clave)",
     {"X-DDP-Timestamp": ts, "X-DDP-Node": "Otro-Nodo",
      "X-DDP-HMAC2": hmac2_otro, "X-DDP-HMAC": legacy}, 200),
    ("4) sin firma", {}, 403),
]

print(f"\n{'CASO':<26} {'HTTP':<6} esperado  veredicto")
print("-" * 60)
todo = True
for etq, hd, esp in casos:
    st = pide(hd)
    bien = (st == esp)
    todo = todo and bien
    print(f"{etq:<26} {str(st):<6} {esp:<9} {'OK' if bien else 'MAL'}")
print("-" * 60)
print("END-TO-END:", "TODO OK" if todo else "HAY FALLOS")
