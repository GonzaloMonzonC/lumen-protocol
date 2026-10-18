#!/usr/bin/env python3
"""1) Quien es 192.168.1.14:8140 (neferu?). 2) El Asus 192.168.1.20: consola M + shell."""
import json, socket, time, urllib.request

# ── 1) la puerta LLM ──
print("=== 192.168.1.14:8140 (la puerta LLM) ===")
try:
    with urllib.request.urlopen("http://192.168.1.14:8140/health", timeout=8) as r:
        print("  /health ->", r.status, r.read().decode()[:180])
except Exception as e:
    print("  /health ERR:", e)
try:
    with urllib.request.urlopen("http://192.168.1.14:8140/", timeout=8) as r:
        print("  /       ->", r.status, r.read().decode()[:120])
except urllib.error.HTTPError as e:
    print("  /       ->", e.code, e.read().decode()[:120])
except Exception as e:
    print("  /       ERR:", e)


# ── 2) telnet minimo ──
class T:
    def __init__(self, host, port, t=12):
        self.s = socket.create_connection((host, port), timeout=t)
        self.s.settimeout(t)

    def leer(self, seg=3.0):
        fin = time.time() + seg
        out = b""
        while time.time() < fin:
            try:
                d = self.s.recv(4096)
                if not d:
                    break
                out += d
            except socket.timeout:
                break
        return out

    def manda(self, txt, seg=4.0):
        self.s.sendall(txt.encode() + b"\r\n")
        return self.leer(seg)

    def cierra(self):
        try:
            self.s.close()
        except Exception:
            pass


def limpia(b):
    # quita negociacion IAC: 0xFF + 2 bytes
    out, i = bytearray(), 0
    while i < len(b):
        if b[i] == 0xFF and i + 2 < len(b):
            i += 3
        else:
            out.append(b[i])
            i += 1
    return bytes(out).decode("utf-8", "replace").replace("\r", "")


print("\n=== Asus 192.168.1.20 : puerto 23 (consola M) ===")
try:
    c = T("192.168.1.20", 23)
    print(limpia(c.leer(6))[-700:])
    for cmd in ('/m D ^CONFIG("ddp_peer"),!', '/m D ^CONFIG("nodo_id"),!',
                '/m W $G(^SYS("NODO")),!'):
        print(f"\n  >>> {cmd}")
        print(limpia(c.manda(cmd, 5))[-300:])
    c.cierra()
except Exception as e:
    print("  ERR:", e)

print("\n=== Asus 192.168.1.20 : puerto 2323 (shell) ===")
try:
    c = T("192.168.1.20", 2323)
    c.leer(4)
    for cmd in ("ip -4 addr show | grep -v lo", "cat /tmp/nodo.log | tail -6"):
        print(f"\n  >>> {cmd}")
        print(limpia(c.manda(cmd, 5))[-600:])
    c.cierra()
except Exception as e:
    print("  ERR:", e)
