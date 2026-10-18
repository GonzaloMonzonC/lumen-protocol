#!/usr/bin/env python3
"""FIX: telnetd necesita /dev/pts montado (devpts) para crear la PTY.
El init lo monta pronto, pero /dev se remonta despues y /dev/pts desaparece:
medido -> '[telnet] devpts: NO' y telnetd acepta la conexion y la cierra."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

old = '''if [ "$TELNET_ON" = "si" ] && [ -x /etc/telnet-m.sh ]; then
    /bin/busybox telnetd -p "$TELNET_PUERTO" -l /etc/telnet-m.sh >/tmp/telnetd.log 2>&1'''

new = '''if [ "$TELNET_ON" = "si" ] && [ -x /etc/telnet-m.sh ]; then
    # telnetd necesita una PTY: sin /dev/pts montado acepta y cierra al instante
    [ -d /dev/pts ] || mkdir -p /dev/pts 2>/dev/null
    /bin/busybox mount -t devpts devpts /dev/pts 2>/dev/null
    echo "[telnet] devpts tras montar: $([ -d /dev/pts ] && echo si || echo NO)"
    /bin/busybox telnetd -p "$TELNET_PUERTO" -l /etc/telnet-m.sh >/tmp/telnetd.log 2>&1'''

assert old in s, "no encontre el arranque de telnetd"
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
import py_compile
py_compile.compile(P, doraise=True)
print("PATCH OK: devpts antes de telnetd")
