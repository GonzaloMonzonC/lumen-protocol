#!/usr/bin/env python3
"""¿Estan los modulos de cripto que mac80211 necesita para instalar una clave CCMP?"""
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


def sh(cmd, seg=12):
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


for etq, cmd in [
    ("modulos de cripto CARGADOS", "lsmod | grep -iE 'aes|ccm|gcm|crypto|crc32|sha1|md5' | head -12"),
    ("existen los .ko en el nodo?", "ls /lib/modules/*/kernel/crypto/ 2>/dev/null | head -12; echo '---'; find / -name 'ccm.ko*' -o -name 'aes*.ko*' 2>/dev/null | head -6"),
    ("lib80211 (lo usa mac80211)", "lsmod | grep lib80211; ls /lib/modules/*/kernel/net/wireless/ 2>/dev/null | head -10"),
    ("dmesg: errores de cripto", "dmesg | grep -iE 'crypto|ccm|aes|cipher|key' | tail -8"),
    ("mac80211 parametros", "ls /sys/module/mac80211/parameters/ 2>/dev/null | head -12"),
]:
    print(f"\n=== {etq} ===")
    print("   " + sh(cmd).replace("\n", "\n   "))
