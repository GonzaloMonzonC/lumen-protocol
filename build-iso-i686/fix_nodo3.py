#!/usr/bin/env python3
"""Corrige el bloque NODO: SIN backslashes."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

ini = s.find('NODO_BLOCK = b"""')
assert ini != -1, "no encontre NODO_BLOCK"
fin = s.find('"""', ini + len('NODO_BLOCK = b"""'))
assert fin != -1
fin += 3

LINEAS = [
    "",
    "# --- NOMBRE DEL NODO: de ESTA maquina (no del seed de la PDB) ---",
    '# ^SYS("NODO") venia SEMBRADO como NAS02 (DS216se) y TODAS las maquinas se',
    "# identificaban igual. Orden: /etc/nodo.conf -> cmdline nodo= -> DMI.",
    'NODO_N=""',
    "if [ -f /etc/nodo.conf ]; then",
    "    NODO_N=$(sed -n 's/^[[:space:]]*NODO=//p' /etc/nodo.conf 2>/dev/null | head -1)",
    "fi",
    "for _a in $(cat /proc/cmdline 2>/dev/null); do",
    '    case "$_a" in nodo=*) NODO_N="${_a#nodo=}" ;; esac',
    "done",
    'if [ -z "$NODO_N" ] || [ "$NODO_N" = "auto" ]; then',
    "    _V=$(cat /sys/class/dmi/id/sys_vendor 2>/dev/null)",
    "    _P=$(cat /sys/class/dmi/id/product_name 2>/dev/null)",
    "    _F=$(cat /sys/class/dmi/id/board_name 2>/dev/null)",
    '    case "$_V" in',
    '        *ASUSTeK*|*ASUS*) _V="Asus" ;;',
    '        *Acer*) _V="Acer" ;;',
    '        *Hewlett*|*HP*) _V="HP" ;;',
    '        *Lenovo*) _V="Lenovo" ;;',
    '        *IBM*) _V="IBM" ;;',
    '        *eMachines*) _V="eMachines" ;;',
    '        *Synology*) _V="Synology" ;;',
    "    esac",
    '    [ -n "$_P" ] || _P="$_F"',
    '    NODO_N="$_V $_P"',
    "fi",
    "NODO_N=$(echo \"$NODO_N\" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')",
    '[ -n "$NODO_N" ] || NODO_N="nodo LUMEN"',
    # comillas simples+dobles concatenadas: M recibe  S ^SYS("NODO")="Asus 1005HA"
    "_CMD='S ^SYS(\"NODO\")=\"'\"$NODO_N\"'\"'",
    'if /opt/mvm/mvm-nas -p "$PDB" -r /opt/mvm/routines -e "$_CMD" >/tmp/nodo.log 2>&1; then',
    '    echo "[nodo] nombre de ESTA maquina: $NODO_N"',
    "else",
    '    echo "[nodo] !! no se pudo fijar el nombre (ver /tmp/nodo.log)"',
    "fi",
    "",
]
cuerpo = "\n".join(LINEAS)

# el bloque se monta por concatenacion de bytes -> evita TODO problema de escapes
NUEVO = 'NODO_BLOCK = b"""\\n' + cuerpo + '"""'
s = s[:ini] + NUEVO + s[fin:]

old = '''        data = open(s, "rb").read().replace(b"@VERSION@", b"v" + ver.encode())'''
new = '''        data = open(s, "rb").read().replace(b"@VERSION@", b"v" + ver.encode())
        if f.endswith(".conf") or f.endswith(".script"):
            data = data.replace(b"\\r\\n", b"\\n")'''
assert old in s, "no encontre la lectura"
s = s.replace(old, new, 1)

open(P, "w", encoding="utf-8", newline="").write(s)
import py_compile
py_compile.compile(P, doraise=True)
print("PATCH OK y compila")
print("--- valor real de NODO_BLOCK (ultimas lineas) ---")
ns = {}
exec(compile(open(P, encoding="utf-8").read().split("def ")[0], P, "exec"), ns)
print("\\n".join(ns["NODO_BLOCK"].decode().splitlines()[-6:]))
