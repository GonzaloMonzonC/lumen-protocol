#!/usr/bin/env python3
"""Diagnostico telnet: las lineas son CRUDAS dentro del bytes-literal."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

old = '''if [ "$TELNET_ON" = "si" ] && [ -x /etc/telnet-m.sh ]; then
    if /bin/busybox telnetd -p "$TELNET_PUERTO" -l /etc/telnet-m.sh >/tmp/telnetd.log 2>&1; then'''

new = '''echo "[telnet] telnet-m.sh -> $(ls -l /etc/telnet-m.sh 2>&1)"
echo "[telnet] ptmx: $([ -e /dev/ptmx ] && echo si || echo NO)"
echo "[telnet] devpts: $([ -d /dev/pts ] && echo si || echo NO)"
if [ "$TELNET_ON" = "si" ] && [ -x /etc/telnet-m.sh ]; then
    /bin/busybox telnetd -p "$TELNET_PUERTO" -l /etc/telnet-m.sh >/tmp/telnetd.log 2>&1
    sleep 2
    echo "[telnet] escuchando:"
    /bin/busybox netstat -ltn 2>/dev/null | grep ":$TELNET_PUERTO"
    echo "[telnet] log de telnetd:"
    head -3 /tmp/telnetd.log 2>/dev/null
    if true; then'''

assert old in s, "no encontre el bloque telnet"
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
import py_compile
py_compile.compile(P, doraise=True)
print("PATCH OK (diagnostico telnet)")
