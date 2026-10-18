#!/usr/bin/env python3
"""1) FIX: el bloque del NODO se inyectaba DENTRO del 'while true' (se repetia cada 5 s).
   Ahora va ANTES del bucle.
2) NUEVO: bloque de TELNET (consola M remota)."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

# ---- 1) TELNET_BLOCK (se monta por lineas: cero problemas de escapes) ----
LINEAS = [
    "",
    "# --- ACCESO REMOTO: consola M por telnet (ver /etc/telnet.conf) ---",
    '# El nodo no tiene teclado ni monitor: esto da la MISMA consola M remota.',
    '# telnet va en claro y sin contrasena -> solo vale en red local aislada.',
    'TELNET_ON="si"',
    "TELNET_PUERTO=23",
    "if [ -f /etc/telnet.conf ]; then",
    "    _t=$(sed -n 's/^[[:space:]]*TELNET=//p' /etc/telnet.conf 2>/dev/null | head -1)",
    '    [ -n "$_t" ] && TELNET_ON="$_t"',
    "    _pu=$(sed -n 's/^[[:space:]]*PUERTO=//p' /etc/telnet.conf 2>/dev/null | head -1)",
    '    [ -n "$_pu" ] && TELNET_PUERTO="$_pu"',
    "fi",
    'if [ "$TELNET_ON" = "si" ] && [ -x /etc/telnet-m.sh ]; then',
    '    if /bin/busybox telnetd -p "$TELNET_PUERTO" -l /etc/telnet-m.sh'
    " >/tmp/telnetd.log 2>&1; then",
    '        echo "[telnet] consola M en el puerto $TELNET_PUERTO · entra: telnet <IP> $TELNET_PUERTO"',
    "    else",
    '        echo "[telnet] !! no se pudo abrir el puerto $TELNET_PUERTO (ver /tmp/telnetd.log)"',
    "    fi",
    "else",
    '    echo "[telnet] cerrado (TELNET=no en /etc/telnet.conf, o falta telnet-m.sh)"',
    "fi",
    "",
]
telnet_block = 'TELNET_BLOCK = b"""\\n' + "\n".join(LINEAS) + '"""\n'

# insertar la constante justo antes de NODO_BLOCK
i = s.find("NODO_BLOCK = b")
assert i != -1, "no encontre NODO_BLOCK"
s = s[:i] + telnet_block + "\n" + s[i:]

# ---- 2) corregir la inyeccion: ANTES del while, y con los DOS bloques ----
old = '''                w = data.rfind(b"while true; do", 0, k)
                if w != -1:
                    ins = data.find(b"\\n", w) + 1
                    data = data[:ins] + NODO_BLOCK + data[ins:]
                    print("  init: bloque de NOMBRE DEL NODO inyectado")'''
new = '''                w = data.rfind(b"while true; do", 0, k)
                if w != -1:
                    # ANTES del bucle: si va dentro se repetiria cada 5 s
                    data = data[:w] + NODO_BLOCK + TELNET_BLOCK + data[w:]
                    print("  init: NOMBRE DEL NODO + TELNET inyectados (antes del bucle)")'''
assert old in s, "no encontre la inyeccion del nodo"
s = s.replace(old, new, 1)

open(P, "w", encoding="utf-8", newline="").write(s)
import py_compile
py_compile.compile(P, doraise=True)
print("PATCH OK y compila")
