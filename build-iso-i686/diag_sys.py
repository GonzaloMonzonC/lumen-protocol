#!/usr/bin/env python3
"""WiFi con lo que SI hay en la ISO (no hay iwconfig/rfkill): /proc y /sys."""
import socket, time

NODOS = [("Asus", "192.168.1.20"), ("eMachines", "192.168.1.17")]


def limpia(b):
    out, i = bytearray(), 0
    while i < len(b):
        if b[i] == 0xFF and i + 2 < len(b):
            i += 3
        else:
            out.append(b[i])
            i += 1
    return bytes(out).decode("utf-8", "replace").replace("\r", "")


def sh(ip, cmd, seg=8):
    try:
        s = socket.create_connection((ip, 2323), timeout=25)
        s.settimeout(25)
        time.sleep(0.5)
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
        r = limpia(out)
        return " | ".join(x.strip() for x in r.split("\n")
                          if x.strip() and cmd not in x and not x.startswith("/ #"))
    except Exception as e:
        return f"(ERR {e})"


CMDS = [
    ("interfaces", "ls /sys/class/net"),
    ("/proc/net/wireless", "cat /proc/net/wireless 2>&1 | tail -3"),
    ("estado de cada if", "for i in $(ls /sys/class/net); do echo -n \"$i=\"; cat /sys/class/net/$i/operstate 2>/dev/null | tr -d '\\n'; echo -n ' '; done"),
    ("driver de cada if", "for i in $(ls /sys/class/net); do echo -n \"$i:\"; basename $(readlink -f /sys/class/net/$i/device/driver 2>/dev/null) 2>/dev/null; done"),
    ("rfkill (sys)", "for r in /sys/class/rfkill/*; do echo -n \"$(basename $r):\"; cat $r/type 2>/dev/null | tr -d '\\n'; echo -n ' soft='; cat $r/soft 2>/dev/null | tr -d '\\n'; echo -n ' hard='; cat $r/hard 2>/dev/null; done"),
    ("dmesg wifi", "dmesg 2>/dev/null | grep -iE 'ath9k|ipw2200|b43|firmware|wlan|80211' | tail -6"),
    ("ver ISO (modulos)", "grep -ac 'MODULOS' /tmp/nodo.log 2>/dev/null; grep -a 'MODULOS' /tmp/nodo.log 2>/dev/null | tail -1"),
    ("rutinas cargadas", "grep -ac 'rutina(s) cargada' /tmp/nodo.log; grep -a 'rutina(s) cargada' /tmp/nodo.log | tail -1"),
]

for etq, ip in NODOS:
    print("=" * 72)
    print(f"{etq} ({ip})")
    for nombre, cmd in CMDS:
        print(f"  -- {nombre}")
        print(f"     {sh(ip, cmd)}")
