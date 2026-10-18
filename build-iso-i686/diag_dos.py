#!/usr/bin/env python3
"""Diagnostico de los DOS nodos: Asus .20 y TravelMate .22 (via Ethernet)."""
import hashlib, hmac, json, re, socket, time, urllib.request, urllib.error
from pathlib import Path

KEY = re.search(r"^DDP_KEY=(.+)$",
                Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/hub.conf")
                .read_text(encoding="utf-8"), re.M).group(1).strip()


def hub(path):
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


def limpia(b):
    out, i = bytearray(), 0
    while i < len(b):
        if b[i] == 0xFF and i + 2 < len(b):
            i += 3
        else:
            out.append(b[i])
            i += 1
    return bytes(out).decode("utf-8", "replace").replace("\r", "")


def puerto(ip, p):
    try:
        s = socket.create_connection((ip, p), timeout=5)
        s.close()
        return True
    except Exception:
        return False


def sh(ip, cmd, seg=10):
    """Comando por el shell :2323."""
    if not puerto(ip, 2323):
        return f"(sin shell :2323 en {ip})"
    try:
        s = socket.create_connection((ip, 2323), timeout=30)
        s.settimeout(30)
        time.sleep(0.6)
        s.recv(65536)
        s.sendall(cmd.encode() + b"\r\n")
        time.sleep(seg / 10)
        out, fin = b"", time.time() + seg
        while time.time() < fin:
            try:
                d = s.recv(16384)
                if not d:
                    break
                out += d
            except socket.timeout:
                break
        s.close()
        r = limpia(out)
        return "\n".join(x.rstrip() for x in r.split("\n")
                         if x.strip() and cmd not in x and not x.startswith("/ #"))
    except Exception as e:
        return f"(ERR {e})"


NODOS = [("Asus", "192.168.1.20"), ("TravelMate", "192.168.1.22")]

print("=" * 70)
print("REGISTRO DEL HUB (GET /ddp/nodes)")
d = hub("/ddp/nodes")
if isinstance(d, dict) and "nodos" in d:
    print(f"  n = {d.get('n')}")
    for k, v in (d["nodos"] or {}).items():
        print(f"   · {k}: ip={v.get('ip')} cpu={str(v.get('cpu'))[:32]} ram={v.get('ram_mb')} ultima={v.get('ultima')}")
else:
    print("  ", d)

for etq, ip in NODOS:
    print("\n" + "=" * 70)
    print(f"{etq}  ({ip})")
    print(f"  telnet 23 (consola M): {'ABIERTO' if puerto(ip, 23) else 'cerrado'}")
    print(f"  telnet 2323 (shell):   {'ABIERTO' if puerto(ip, 2323) else 'cerrado'}")
    if not puerto(ip, 2323):
        continue
    print("  --- interfaces y driver ---")
    print("   ", sh(ip, "ip -o link show | awk '{print $2}'"))
    print("   ", sh(ip, "iwconfig 2>&1 | head -6"))
    print("  --- ¿wifi detectada por el init? ---")
    print("   ", sh(ip, "grep -a 'wifi' /tmp/nodo.log | head -8"))
    print("  --- modulo wifi cargado ---")
    print("   ", sh(ip, "lsmod | grep -iE 'ipw2200|ath9k|b43|iwl' | head -4"))
    print("  --- rfkill ---")
    print("   ", sh(ip, "rfkill list 2>&1 | head -6 || echo '(sin rfkill)'"))
    print("  --- escaneo ---")
    print("   ", sh(ip, "iwlist eth0 scan 2>&1 | head -8"))
