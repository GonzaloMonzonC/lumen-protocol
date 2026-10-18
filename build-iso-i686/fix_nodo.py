#!/usr/bin/env python3
"""El nodo debe llamarse como SU maquina, no 'NAS02 (DS216se)'.
^SYS("NODO") viene SEMBRADO en la PDB y todas las maquinas se identificaban igual.
Ahora: /etc/nodo.conf -> cmdline nodo= -> DMI (fabricante + modelo) -> ultimo recurso."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

BLOQUE = '''
        if f == "init":
            hook = (b"# --- LUMEN i686: precarga de dependencias (ver lumenos-preload.sh) ---\\n"
                    b"if [ -f /etc/lumenos-preload.sh ]; then . /etc/lumenos-preload.sh; fi\\n")
            marker = b"[hardware] cargando drivers base"
            i = data.find(marker)
            if i != -1:
                j = data.rfind(b"\\n", 0, i) + 1
                data = data[:j] + hook + data[j:]
                print("  init: hook de preload inyectado")
            # ---- NOMBRE DEL NODO: de LA MAQUINA, no del seed ----
            chat = b'/opt/mvm/mvm-nas -p "$PDB" -r /opt/mvm/routines --chat'
            k = data.find(chat)
            if k != -1:
                w = data.rfind(b"while true; do", 0, k)
                if w != -1:
                    ins = data.find(b"\\n", w) + 1
                    data = data[:ins] + NODO_BLOCK + data[ins:]
                    print("  init: bloque de NOMBRE DEL NODO inyectado")
'''
old = '''        if f == "init":
            hook = (b"# --- LUMEN i686: precarga de dependencias (ver lumenos-preload.sh) ---\\n"
                    b"if [ -f /etc/lumenos-preload.sh ]; then . /etc/lumenos-preload.sh; fi\\n")
            marker = b"[hardware] cargando drivers base"
            i = data.find(marker)
            if i != -1:
                j = data.rfind(b"\\n", 0, i) + 1
                data = data[:j] + hook + data[j:]
                print("  init: hook de preload inyectado")
'''
assert old in s, "no encontre el bloque init"
s = s.replace(old, BLOQUE, 1)

# el texto del bloque (constante global, antes de la funcion que lo usa)
NODO_TXT = '''
NODO_BLOCK = b"""
# --- NOMBRE DEL NODO: de ESTA maquina (no del seed de la PDB) ---
# ^SYS("NODO") venia SEMBRADO como "NAS02 (DS216se)" y TODAS las maquinas se
# identificaban igual. Orden: /etc/nodo.conf -> cmdline nodo= -> DMI.
NODO_N=""
if [ -f /etc/nodo.conf ]; then
    NODO_N=$(sed -n 's/^[[:space:]]*NODO=//p' /etc/nodo.conf 2>/dev/null | head -1 | tr -d '\\r')
fi
for _a in $(cat /proc/cmdline 2>/dev/null); do
    case "$_a" in nodo=*) NODO_N="${_a#nodo=}" ;; esac
done
if [ -z "$NODO_N" ] || [ "$NODO_N" = "auto" ]; then
    _V=$(cat /sys/class/dmi/id/sys_vendor 2>/dev/null | tr -d '\\r\\n')
    _P=$(cat /sys/class/dmi/id/product_name 2>/dev/null | tr -d '\\r\\n')
    _F=$(cat /sys/class/dmi/id/board_name 2>/dev/null | tr -d '\\r\\n')
    case "$_V" in
        *ASUSTeK*|*ASUS*)   _V="Asus" ;;
        *Acer*)             _V="Acer" ;;
        *Hewlett*|*HP*)     _V="HP" ;;
        *Lenovo*)           _V="Lenovo" ;;
        *IBM*)              _V="IBM" ;;
        *eMachines*)        _V="eMachines" ;;
        *Synology*)         _V="Synology" ;;
    esac
    [ -n "$_P" ] || _P="$_F"
    NODO_N="$_V $_P"
fi
NODO_N=$(echo "$NODO_N" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
[ -n "$NODO_N" ] || NODO_N="nodo LUMEN"
if /opt/mvm/mvm-nas -p "$PDB" -r /opt/mvm/routines \\
        -e "S ^SYS(\\"NODO\\")=\\"$NODO_N\\"" >/tmp/nodo.log 2>&1; then
    echo "[nodo] nombre de ESTA maquina: $NODO_N"
else
    echo "[nodo] !! no se pudo fijar el nombre (ver /tmp/nodo.log)"
fi
"""
'''
anchor2 = "\ndef copy_seed():"
assert anchor2 in s, "no encontre copy_seed para anclar NODO_BLOCK"
s = s.replace(anchor2, NODO_TXT + anchor2, 1)

open(P, "w", encoding="utf-8", newline="").write(s)
import py_compile
py_compile.compile(P, doraise=True)
print("PATCH OK y compila")
