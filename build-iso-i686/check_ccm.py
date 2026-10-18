#!/usr/bin/env python3
"""¿Se puede CARGAR ccm? (si modprobe falla, es el modules.dep de la ISO)."""
import socket, time

IP = "192.168.1.20"


def limpia(b):
    out, i = bytearray(), 0
    while i < len(b):
        if b[i] == 0xFF and i + 2 < len(b):
            i += 3
        else:
            out.append(b[i])
            i += 1
    return bytes(out).decode("utf-8", "replace").replace("\r", "")


def sh(cmd, seg=14):
    s = socket.create_connection((IP, 2323), timeout=60)
    s.settimeout(60)
    time.sleep(0.4)
    s.recv(65536)
    s.sendall(cmd.encode() + b"\r\n")
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
    return limpia(out)


for etq, c in [
    ("ccm cargado?", "lsmod | grep ccm || echo NO"),
    ("modprobe ccm", "modprobe ccm 2>&1; echo rc=$?"),
    ("tras modprobe", "lsmod | grep ccm || echo NO"),
    ("esta el .ko?", "ls /lib/modules/*/kernel/crypto/ | head -12"),
    ("lo ve depmod?", "grep -c ccm /lib/modules/*/modules.dep 2>/dev/null || echo 0"),
    ("mac80211 pide ccm?", "modinfo mac80211 2>/dev/null | grep -iE 'depends|firmware' | head -2"),
]:
    print(f"--- {etq}")
    print("    " + sh(c).replace("\n", "\n    ")[:600])
