#!/usr/bin/env python3
"""Dos puertos telnet: PUERTO=consola M (gestionar) + SHELL_PUERTO=shell (diagnosticar)."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

old = '''# --- ACCESO REMOTO: consola M por telnet (ver /etc/telnet.conf) ---
# El nodo no tiene teclado ni monitor: esto da la MISMA consola M remota.
# telnet va en claro y sin contrasena -> solo vale en red local aislada.
TELNET_ON="si"
TELNET_PUERTO=23
if [ -f /etc/telnet.conf ]; then
    _t=$(sed -n 's/^[[:space:]]*TELNET=//p' /etc/telnet.conf 2>/dev/null | head -1)
    [ -n "$_t" ] && TELNET_ON="$_t"
    _pu=$(sed -n 's/^[[:space:]]*PUERTO=//p' /etc/telnet.conf 2>/dev/null | head -1)
    [ -n "$_pu" ] && TELNET_PUERTO="$_pu"
fi
if [ "$TELNET_ON" = "si" ] && [ -x /etc/telnet-m.sh ]; then
    # telnetd necesita una PTY: si /dev/pts no esta montado, acepta y cierra al instante
    [ -d /dev/pts ] || mkdir -p /dev/pts 2>/dev/null
    /bin/busybox mount -t devpts devpts /dev/pts 2>/dev/null
    if /bin/busybox telnetd -p "$TELNET_PUERTO" -l /etc/telnet-m.sh >/tmp/telnetd.log 2>&1; then
        echo "[telnet] consola M en el puerto $TELNET_PUERTO - entra: telnet <IP> $TELNET_PUERTO"
    else
        echo "[telnet] !! no se pudo abrir el puerto $TELNET_PUERTO (ver /tmp/telnetd.log)"
    fi
else
    echo "[telnet] cerrado (TELNET=no en /etc/telnet.conf, o falta telnet-m.sh)"
fi'''

new = '''# --- ACCESO REMOTO por telnet (ver /etc/telnet.conf) ---
# El nodo no tiene teclado ni monitor. DOS puertos con dos usos distintos:
#   PUERTO       -> CONSOLA M: gestionar el nodo (/top, /m <M>, /m :save, /ag...)
#   SHELL_PUERTO -> SHELL DEL SISTEMA: diagnosticar (iwconfig, dmesg, cat...)
# Los dos van en claro y sin contrasena -> SOLO valen en red local aislada.
TELNET_ON="si"
TELNET_PUERTO=23
SHELL_ON="si"
SHELL_PUERTO=2323
if [ -f /etc/telnet.conf ]; then
    _t=$(sed -n 's/^[[:space:]]*TELNET=//p' /etc/telnet.conf 2>/dev/null | head -1)
    [ -n "$_t" ] && TELNET_ON="$_t"
    _pu=$(sed -n 's/^[[:space:]]*PUERTO=//p' /etc/telnet.conf 2>/dev/null | head -1)
    [ -n "$_pu" ] && TELNET_PUERTO="$_pu"
    _sh=$(sed -n 's/^[[:space:]]*SHELL=//p' /etc/telnet.conf 2>/dev/null | head -1)
    [ -n "$_sh" ] && SHELL_ON="$_sh"
    _sp=$(sed -n 's/^[[:space:]]*SHELL_PUERTO=//p' /etc/telnet.conf 2>/dev/null | head -1)
    [ -n "$_sp" ] && SHELL_PUERTO="$_sp"
fi
# telnetd necesita una PTY: si /dev/pts no esta montado, acepta y cierra al instante
[ -d /dev/pts ] || mkdir -p /dev/pts 2>/dev/null
/bin/busybox mount -t devpts devpts /dev/pts 2>/dev/null
if [ "$TELNET_ON" = "si" ] && [ -x /etc/telnet-m.sh ]; then
    if /bin/busybox telnetd -p "$TELNET_PUERTO" -l /etc/telnet-m.sh >/tmp/telnetd.log 2>&1; then
        echo "[telnet] consola M en :$TELNET_PUERTO (gestionar el nodo)"
    else
        echo "[telnet] !! consola M: no se pudo abrir el :$TELNET_PUERTO"
    fi
else
    echo "[telnet] consola M cerrada (TELNET=no)"
fi
if [ "$SHELL_ON" = "si" ] && [ -x /etc/telnet-sh.sh ]; then
    if /bin/busybox telnetd -p "$SHELL_PUERTO" -l /etc/telnet-sh.sh >/tmp/telnetd-sh.log 2>&1; then
        echo "[telnet] shell del sistema en :$SHELL_PUERTO (diagnostico, root)"
    else
        echo "[telnet] !! shell: no se pudo abrir el :$SHELL_PUERTO"
    fi
else
    echo "[telnet] shell cerrado (SHELL=no)"
fi'''

assert old in s, "no encontre el bloque telnet"
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
import py_compile
py_compile.compile(P, doraise=True)
print("PATCH OK: dos puertos telnet")
