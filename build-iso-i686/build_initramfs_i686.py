#!/usr/bin/env python3
"""
Construye el initramfs de LUMEN OS i686 (32 bits) a partir de:
  - kernel Debian i386 6.1.0-50-686 (assets/kernel-root)
  - busybox-static i386   (assets/busybox-root/bin/busybox)
  - nodo mvm-nas-i686     (mvm-nas/deploy/bin/mvm-nas-i686-musl)
  - init + helpers        (mvm-nas/lumenos/rootfs)
Empaqueta en cpio-newc + gzip (sin depender de cpio del sistema).
"""
import os, re, gzip, struct, sys, shutil
import glob

HOME = "C:/Users/gonzalo"
PROTO = f"{HOME}/Documents/GitHub/lumen-protocol"
MVN = f"{HOME}/Documents/GitHub/mvm-nas"
B = f"{PROTO}/build-iso-i686"
KVER = "6.1.0-50-686"
SRC_MOD = f"{B}/assets/kernel-root/lib/modules/{KVER}"
OUT = f"{B}/initramfs-i686"
ROOTFS = f"{MVN}/lumenos/rootfs"

# Lista curada (adaptada de lumenos/_build_initramfs.sh MODS=) con los drivers
# que importan para arrancar en PCs antiguos: red cable+WiFi, USB, SATA/IDE, video.
MODS = """
cfg80211 mac80211 libarc4 rfkill
iwlwifi iwlmvm iwldvm iwlegacy iwl3945 iwl4965
ath9k ath9k_htc ath9k_common ath9k_hw ath5k ath
brcmfmac brcmutil bcma ssb b43 b43legacy
rtl8xxxu rtl8192cu rtl8188ee rtl8192ce rtl8723be rtl8192se
rtlwifi rtl_pci rtl_usb rtl8723-common
rt2x00lib rt2x00usb rt2x00pci rt2800lib rt2800usb rt73usb crc-itu-t
mt7601u mt76x0u mt76x2u mt76x02-lib mt76-usb zd1211rw libertas mwl8k
simpledrm drm drm_kms_helper
8139too 8139cp sky2 tg3 via-rhine sis900 forcedeth e100 e1000 e1000e r8169 b44
3c59x pcnet32 tulip ne2k-pci 8390 depca hp100 sundance fealnx ns83820
usbnet cdc_ether rndis_host asix mii
evdev mousedev psmouse atkbd
brcmsmac rtl8187 rtl8192c-common
"""


def norm(s):
    return " ".join(s.split())


def index_modules():
    """basename sin .ko -> ruta completa del .ko"""
    idx = {}
    for dirpath, _, files in os.walk(SRC_MOD):
        for f in files:
            if f.endswith(".ko"):
                name = f[:-3]
                idx.setdefault(name, os.path.join(dirpath, f))
    print(f"  modulos en el kernel Debian: {len(idx)}")
    return idx


def ko_depends(path):
    """lee depends= del .modinfo del .ko (mismo dato que modinfo -F depends)"""
    with open(path, "rb") as fh:
        blob = fh.read()
    m = re.search(rb"depends=([^\x00\n]*)", blob)
    if not m:
        return []
    raw = m.group(1).decode("utf-8", "replace").strip()
    if not raw:
        return []
    return [d for d in raw.split(",") if d]


def modprobe_names_from_init():
    """extrae los nombres que el init carga con 'for X in A B C;' y 'modprobe N'"""
    p = os.path.join(ROOTFS, "init")
    txt = open(p, encoding="utf-8", errors="replace").read()
    txt = re.sub(r"#.*", "", txt)          # fuera comentarios
    txt = txt.replace("\\\n", " ")          # unir continuaciones
    names = set()
    for m in re.finditer(r"for\s+[A-Za-z_]\w*\s+in\s+([^;]+);", txt):
        for w in m.group(1).split():
            if re.fullmatch(r"[a-z0-9_-]+", w):
                names.add(w)
    for m in re.finditer(r"\bmodprobe\s+([a-z0-9_-]+)", txt):
        names.add(m.group(1))
    return names


def closure(mods, idx):
    need, stack = set(), list(mods)
    missing = []
    while stack:
        n = stack.pop()
        if n in need:
            continue
        if n not in idx:
            missing.append(n)
            continue
        need.add(n)
        for d in ko_depends(idx[n]):
            if d and d not in need:
                stack.append(d)
    return need, missing


FW_DIR = f"{B}/assets/fw-root/lib/firmware"
FW_FILES = [
    "ipw2200-bss.fw", "ipw2200-ibss.fw", "ipw2200-sniffer.fw",
    "iwlwifi-3945-2.ucode",
    "htc_7010.fw", "htc_9271.fw",
]


WPA_ROOT = f"{B}/assets/wpa-root"
WPA_LIB = f"{WPA_ROOT}/lib/i386-linux-gnu"
import struct

WPA_BUSQ = [WPA_LIB, f"{WPA_ROOT}/usr/lib/i386-linux-gnu",
            f"{WPA_ROOT}/lib", f"{WPA_ROOT}/usr/lib"]


def _elf_needed(path):
    """(interp, [DT_NEEDED]) de un ELF de 32 bits. Sin ldd."""
    d = open(path, "rb").read()
    if d[:4] != b"\x7fELF" or d[4] != 1:
        return None, []
    phoff = struct.unpack_from("<I", d, 28)[0]
    phes = struct.unpack_from("<H", d, 42)[0]
    phnum = struct.unpack_from("<H", d, 44)[0]
    dyn, loads = None, []
    for i in range(phnum):
        o = phoff + i * phes
        t = struct.unpack_from("<I", d, o)[0]
        po = struct.unpack_from("<I", d, o + 4)[0]
        pv = struct.unpack_from("<I", d, o + 8)[0]
        pz = struct.unpack_from("<I", d, o + 16)[0]
        if t == 2:
            dyn = (po, pz)
        elif t == 1:
            loads.append((pv, po, pz))
    if not dyn:
        return None, []

    def v2o(v):
        for va, off, sz in loads:
            if va <= v < va + sz:
                return off + (v - va)
    o, z = dyn
    ents, strv = [], None
    for j in range(0, z, 8):
        tag, val = struct.unpack_from("<II", d, o + j)
        if tag == 0:
            break
        ents.append((tag, val))
        if tag == 5:
            strv = val
    need = []
    if strv is not None:
        so = v2o(strv)
        for tag, val in ents:
            if tag == 1:
                p = so + val
                need.append(d[p:d.index(b"\x00", p)].decode())
    return None, need


def _find_so(name):
    for d in WPA_BUSQ:
        if os.path.exists(f"{d}/{name}"):
            return os.path.realpath(f"{d}/{name}")
    return None


def _wpa_closure(roots):
    """cierre transitivo: devuelve {SONAME: ruta_real} (el loader busca el SONAME)."""
    seen, out = set(), {}
    stack = [r for r in roots if os.path.isfile(r)]
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        _, need = _elf_needed(p)
        for n in need:
            q = _find_so(n)
            if q:
                out[n] = q
                if q not in seen:
                    stack.append(q)
    return out


def copy_wpa():
    """wpa_supplicant es glibc (dinamico): hay que llevar el binario + el
    enlazador (/lib/ld-linux.so.2, lo que dice PT_INTERP) + sus .so.
    Sin esto, el WiFi solo vale para redes abiertas."""
    src = f"{WPA_ROOT}/sbin/wpa_supplicant"
    if not os.path.isfile(src):
        print("  !! wpa_supplicant no encontrado (¿get_wpa.py?)")
        return
    os.makedirs(f"{OUT}/lib/i386-linux-gnu", exist_ok=True)
    shutil.copy2(src, f"{OUT}/bin/wpa_supplicant")
    ld = f"{WPA_LIB}/ld-linux.so.2"
    if os.path.exists(ld):
        real = os.path.realpath(ld)
        shutil.copy2(real, f"{OUT}/lib/ld-linux.so.2")
        shutil.copy2(real, f"{OUT}/lib/i386-linux-gnu/ld-linux.so.2")
    cli = f"{WPA_ROOT}/sbin/wpa_cli"
    libs = _wpa_closure([src, cli])
    n = 0
    for soname, p in libs.items():
        if os.path.basename(p).startswith("ld-"):
            continue          # el loader va aparte, en /lib/ld-linux.so.2
        shutil.copy2(p, f"{OUT}/lib/i386-linux-gnu/{soname}")
        n += 1
    # wpa_cli comparte las mismas libs
    if os.path.isfile(cli):
        shutil.copy2(cli, f"{OUT}/bin/wpa_cli")
    # wpa_passphrase: el init lo usa para convertir la clave a PSK hex
    wp = f"{WPA_ROOT}/usr/bin/wpa_passphrase"
    if os.path.isfile(wp):
        shutil.copy2(wp, f"{OUT}/bin/wpa_passphrase")
    # --- Envoltorio para chipsets VIEJOS ---------------------------------
    # ipw2200 (TravelMate) es PRE-mac80211: no habla nl80211. El binario prueba
    # "nl80211,wext" y si el fallback no ocurre, no asocia NUNCA.
    # El ELF real va a /usr/sbin/ (mismo basename -> pidof sigue funcionando).
    os.makedirs(f"{OUT}/usr/sbin", exist_ok=True)
    shutil.move(f"{OUT}/bin/wpa_supplicant", f"{OUT}/usr/sbin/wpa_supplicant")
    envoltorio = """#!/bin/busybox sh
# LUMEN i686: fuerza -D wext en chipsets PRE-mac80211 (no soportan nl80211).
REAL=/usr/sbin/wpa_supplicant
IF=""; PREV=""
for a in "$@"; do
    [ "$PREV" = "-i" ] && IF="$a"
    PREV="$a"
done
EXTRA=""
if [ -n "$IF" ]; then
    DRV=$(basename "$(readlink -f /sys/class/net/$IF/device/driver 2>/dev/null)" 2>/dev/null)
    case "$DRV" in
        ipw2200|ipw2100|hostap|orinoco|airo|atmel|zd1201|prism54|wavelan)
            EXTRA="-D wext" ;;
    esac
    echo "[wifi]   envoltorio: driver='$DRV' -> ${EXTRA:-nl80211,wext (por defecto)}"
fi
exec "$REAL" $EXTRA "$@"
"""
    with open(f"{OUT}/bin/wpa_supplicant", "w", newline="\n") as f:
        f.write(envoltorio)
    print(f"  wpa_supplicant + {n} librerias glibc copiadas")


MVM_REPO = "C:/Users/gonzalo/Documents/GitHub/mvm-nas"


KBD_ROOT = f"{B}/assets/kbd-root"
KM_DIR = f"{B}/assets/keymaps"


def copy_kbd():
    """loadkeys + mapas. Sin loadkeys el teclado se queda en INGLES, y en M
    el caret (^) y el tanto por ciento (%) son obligatorios."""
    lk = f"{KBD_ROOT}/bin/loadkeys"
    if not os.path.isfile(lk):
        print("  !! loadkeys no encontrado (¿get_kbd.py?)")
        return
    shutil.copy2(lk, f"{OUT}/bin/loadkeys")
    _, need = _elf_needed(lk)
    nuevas = 0
    for so in need:
        dst = f"{OUT}/lib/i386-linux-gnu/{so}"
        if os.path.exists(dst):
            continue
        p = _find_so(so)
        if p:
            shutil.copy2(p, dst)
            nuevas += 1
    os.makedirs(f"{OUT}/etc/keymaps", exist_ok=True)
    nm = 0
    for k in ("es", "uk", "de", "fr", "it", "pt"):
        src = f"{KM_DIR}/{k}.map.gz"
        if os.path.isfile(src):
            shutil.copy2(src, f"{OUT}/etc/keymaps/{k}.map.gz")
            nm += 1
    aviso = "OK mapa ESPANOL dentro" if os.path.exists(f"{OUT}/etc/keymaps/es.map.gz") \
        else "!! FALTA es.map.gz"
    print(f"  loadkeys + {nm} mapas de teclado ({nuevas} libs nuevas) · {aviso}")


TELNET_BLOCK = b"""\n
# --- ACCESO REMOTO por telnet (ver /etc/telnet.conf) ---
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
fi
"""

NODO_BLOCK = b"""\n
# --- NOMBRE DEL NODO: de ESTA maquina (no del seed de la PDB) ---
# ^SYS("NODO") venia SEMBRADO como NAS02 (DS216se) y TODAS las maquinas se
# identificaban igual. Orden: /etc/nodo.conf -> cmdline nodo= -> DMI.
NODO_N=""
if [ -f /etc/nodo.conf ]; then
    NODO_N=$(sed -n 's/^[[:space:]]*NODO=//p' /etc/nodo.conf 2>/dev/null | head -1)
fi
for _a in $(cat /proc/cmdline 2>/dev/null); do
    case "$_a" in nodo=*) NODO_N="${_a#nodo=}" ;; esac
done
if [ -z "$NODO_N" ] || [ "$NODO_N" = "auto" ]; then
    _V=$(cat /sys/class/dmi/id/sys_vendor 2>/dev/null)
    _P=$(cat /sys/class/dmi/id/product_name 2>/dev/null)
    _F=$(cat /sys/class/dmi/id/board_name 2>/dev/null)
    case "$_V" in
        *ASUSTeK*|*ASUS*) _V="Asus" ;;
        *Acer*) _V="Acer" ;;
        *Hewlett*|*HP*) _V="HP" ;;
        *Lenovo*) _V="Lenovo" ;;
        *IBM*) _V="IBM" ;;
        *eMachines*) _V="eMachines" ;;
        *Synology*) _V="Synology" ;;
    esac
    [ -n "$_P" ] || _P="$_F"
    NODO_N="$_V $_P"
fi
NODO_N=$(echo "$NODO_N" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
[ -n "$NODO_N" ] || NODO_N="nodo LUMEN"
_CMD='S ^SYS("NODO")="'"$NODO_N"'"'
if /opt/mvm/mvm-nas -p "$PDB" -r /opt/mvm/routines -e "$_CMD" >/tmp/nodo.log 2>&1; then
    echo "[nodo] nombre de ESTA maquina: $NODO_N"
else
    echo "[nodo] !! no se pudo fijar el nombre (ver /tmp/nodo.log)"
fi
"""

def copy_seed():
    """SEED LOCAL: apunta la cadena LLM al nodo-puerta (neferu :8140).
    Sin esto el nodo intenta el proveedor directo y da 401 Authentication Fails.
    El fichero lleva un TOKEN: esta GITIGNORED, NO versionar nunca."""
    conf = f"{MVM_REPO}/lumenos/seed-local.conf"
    if os.path.isfile(conf):
        lineas = [l for l in open(conf, encoding="utf-8").read().splitlines()
                  if l.strip() and not l.lstrip().startswith("#")]
        os.makedirs(f"{OUT}/opt/mvm", exist_ok=True)
        with open(f"{OUT}/opt/mvm/seed-local.m", "w", newline="\n") as f:
            f.write("\n".join(lineas) + "\n")
        print(f"  seed-local.m incluido ({len(lineas)} lineas de M) -> puerta LLM")
    else:
        print("  sin seed-local.conf: el nodo usara el proveedor directo (401 probable)")
    clave = f"{MVM_REPO}/lumenos/serve.key"
    if os.path.isfile(clave):
        with open(f"{OUT}/opt/mvm/serve.key", "w", newline="\n") as f:
            f.write(open(clave, encoding="utf-8").read().strip() + "\n")
        print("  serve.key incluido (la puerta :8140 se abrira con auth)")


def copy_firmware():
    """Copia SOLO el firmware de los drivers que llevamos (el resto son 140 MB inutiles)."""
    dest = f"{OUT}/lib/firmware"
    n = 0
    for rel in FW_FILES:
        src = f"{FW_DIR}/{rel}"
        if os.path.isfile(src):
            d = f"{dest}/{rel}"
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(src, d)
            n += 1
    print(f"  firmware copiado: {n} ficheros")


def topo_order(need, idx):
    """Orden topologico: cada modulo DESPUES de sus dependencias."""
    order, seen = [], set()

    def visit(n):
        if n in seen:
            return
        seen.add(n)
        for d in ko_depends(idx[n]):
            if d in need:
                visit(d)
        order.append(n)

    for n in sorted(need):
        visit(n)
    return order


def write_preload(need, idx):
    """Escribe /etc/lumenos-preload.sh con las DEPENDENCIAS en orden.
    El init lo sourcea antes del bucle de drivers: asi, cuando modprobe pida
    ehci-pci (o ath9k), sus deps (usbcore, cfg80211...) YA estan dentro."""
    order = topo_order(need, idx)
    deps_of = set()
    for n in need:
        for d in ko_depends(idx[n]):
            if d in need:
                deps_of.add(d)
    preload = [m for m in order if m in deps_of]
    body = ["#!/bin/sh",
            "# LUMEN i686 - precarga ORDENADA de dependencias.",
            "# Motivo: el modprobe de busybox-static (Debian) NO carga las deps,",
            "# con lo que ehci-hcd/ath9k/drm fallaban con 'Unknown symbol'.",
            "for m in " + " ".join(preload) + "; do modprobe \"$m\" 2>/dev/null; done",
            "# NICs heredadas de portatiles 2003-2007 que el init NO lista",
            "for m in e100 b44 3c59x pcnet32 tulip ne2k-pci 8390 via-rhine sis900 "
            "8139too r8169 forcedeth sky2; do modprobe \"$m\" 2>/dev/null; done",
            ""]
    with open(f"{OUT}/etc/lumenos-preload.sh", "w", newline="\n") as f:
        f.write("\n".join(body))
    os.chmod(f"{OUT}/etc/lumenos-preload.sh", 0o755)
    print(f"  preload: {len(preload)} dependencias en orden topologico")
    print("   " + " ".join(preload[:12]) + (" ..." if len(preload) > 12 else ""))


def copy_tree():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    for d in ("bin", "sbin", "dev", "proc", "sys", "tmp", "root", "etc",
              "run", "var/run/wpa_supplicant", "var/log",
              "opt/mvm/routines", f"lib/modules/{KVER}"):
        os.makedirs(f"{OUT}/{d}", exist_ok=True)


def main():
    print("== indexando modulos ==")
    idx = index_modules()
    req = set(norm(MODS).split())
    ip = modprobe_names_from_init()
    print(f"  el init pide {len(ip)} nombres; lista curada {len(req)}")
    req |= ip
    need, missing = closure(req, idx)
    print(f"  cierre transitivo: {len(need)} modulos; ausentes {len(missing)}")
    if missing:
        print("  (ausentes, se ignoran):", " ".join(sorted(missing)[:40]))

    print("== copiando modulos ==")
    copy_tree()
    deps_lines = []
    alias_lines = []
    for n in sorted(need):
        src = idx[n]
        rel = os.path.relpath(src, SRC_MOD).replace("\\", "/")
        dst = f"{OUT}/lib/modules/{KVER}/{rel}"
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        with open(src, "rb") as fh:
            blob = fh.read()
        deps = ko_depends(src)
        dep_paths = []
        for d in deps:
            if d in idx:
                dep_paths.append(os.path.relpath(idx[d], SRC_MOD).replace("\\", "/"))
        deps_lines.append(f"{rel}: " + " ".join(dep_paths))
        for am in re.finditer(rb"alias=([^\x00\n]+)", blob):
            alias_lines.append(f"{am.group(1).decode('utf-8','replace')} {n}")
    open(f"{OUT}/lib/modules/{KVER}/modules.dep", "w", newline="\n").write("\n".join(deps_lines) + "\n")
    open(f"{OUT}/lib/modules/{KVER}/modules.alias", "w", newline="\n").write("\n".join(alias_lines) + "\n")
    for extra in ("modules.builtin", "modules.order"):
        s = f"{SRC_MOD}/{extra}"
        if os.path.isfile(s):
            shutil.copy2(s, f"{OUT}/lib/modules/{KVER}/{extra}")

    write_preload(need, idx)
    print("== piezas del sistema ==")
    shutil.copy2(f"{B}/assets/busybox-root/bin/busybox", f"{OUT}/bin/busybox")
    os.chmod(f"{OUT}/bin/busybox", 0o755)
    shutil.copy2(f"{MVN}/deploy/bin/mvm-nas-i686-musl", f"{OUT}/opt/mvm/mvm-nas")
    os.chmod(f"{OUT}/opt/mvm/mvm-nas", 0o755)
    shutil.copy2(f"{MVN}/deploy/mini-pdb.db", f"{OUT}/opt/mvm/mini-pdb.db")
    nr = 0
    # 02-oct-2026: el build x86_64 copiaba routines/ + deploy/ (87) y este solo
    # deploy/ (23) -> la ISO i686 salia SIN 64 rutinas. Ahora igual: primero las
    # del repo, luego deploy/routines que MANDA (trae los parches de la ISO).
    # ── CRIPTO para mac80211 (03-oct-2026) ──
    # SIN aes/ccm, mac80211 NO puede instalar una clave CCMP (WPA2-AES):
    #     nl80211: kernel reports: key addition failed
    #     wlan0: WPA: Failed to set PTK to the driver
    # Medido en el Asus: el dir crypto/ del initramfs solo tenia
    # crct10dif_common.ko. Falla IGUAL en todos los PCs (misma ISO).
    # El AES va COMPILADO en el kernel (no hay aes_generic.ko); lo que faltaba
    # era ccm. El kernel carga estos modulos por nombre cuando los pide.
    _kc = glob.glob(f"{MVN}/../build-iso-i686/assets/kernel-root/lib/modules/*/kernel/crypto") or           glob.glob(f"{B}/assets/kernel-root/lib/modules/*/kernel/crypto")
    _md = glob.glob(f"{OUT}/lib/modules/*")
    if _kc and _md:
        _dst = os.path.join(_md[0], "kernel", "crypto")
        os.makedirs(_dst, exist_ok=True)
        _n = 0
        for _f in ("ccm.ko", "ctr.ko", "gcm.ko", "ghash-generic.ko", "ecb.ko",
                   "cbc.ko", "crc32c_generic.ko", "arc4.ko", "aes_ti.ko", "cmac.ko"):
            _src = os.path.join(_kc[0], _f)
            if os.path.exists(_src):
                shutil.copy2(_src, os.path.join(_dst, _f)); _n += 1
        print(f"  cripto para mac80211: {_n} modulos (ccm = el que faltaba)")
    # 02-oct-2026: iwconfig/iwlist (wireless-tools) para poder diagnosticar la
    # WiFi DENTRO del nodo (en la ISO vieja no estaban y hubo que ir por /sys).
    _eb = f"{os.path.dirname(os.path.abspath(__file__))}/extra-bin"
    if os.path.isdir(_eb):
        os.makedirs(f"{OUT}/bin", exist_ok=True)
        os.makedirs(f"{OUT}/lib", exist_ok=True)
        for f in os.listdir(_eb):
            # las .so van a /lib (el cargador no busca en /bin); el resto a /bin
            # regulatory.db -> /lib/firmware/ (cfg80211 lo pide al arrancar;
            # sin el, el kernel arranca en dominio CORE y puede no instalar la
            # clave del WPA: 'Failed to set PTK to the driver' en el Asus)
            if f.startswith("regulatory.db"):
                os.makedirs(f"{OUT}/lib/firmware", exist_ok=True)
                shutil.copy2(os.path.join(_eb, f), f"{OUT}/lib/firmware/{f}")
                os.chmod(f"{OUT}/lib/firmware/{f}", 0o644)
                continue
            # modulos del kernel (.ko) -> su sitio en el arbol de modulos.
            # ccm.ko es el que faltaba para que mac80211 pueda instalar una
            # clave CCMP (WPA2-AES): sin el, 'key addition failed' en TODOS los PCs.
            if f.endswith(".ko"):
                _km = glob.glob(f"{OUT}/lib/modules/*") or [f"{OUT}/lib/modules/6.1.0-50-686"]
                dest = os.path.join(_km[0], "kernel", "crypto", f)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(os.path.join(_eb, f), dest)
                os.chmod(dest, 0o644)
                continue
            dest = f"{OUT}/lib/{f}" if ".so" in f else f"{OUT}/bin/{f}"
            shutil.copy2(os.path.join(_eb, f), dest)
            os.chmod(dest, 0o755)
        print(f"  herramientas extra: {sorted(os.listdir(_eb))}")
        # ⚠️ 03-oct-2026 (DESPUES de copiar, si no no hay nada que indexar): los
        # .ko de cripto eran INVISIBLES para modprobe porque modules.dep no los
        # listaba -> no se cargaban -> mac80211 sin CCMP -> 'key addition failed'
        # -> fallaba IGUAL en todos los PCs. Se regenera el indice aqui.
        import subprocess as _sp
        _sp.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fix_depmod.py")])
    _r = f"{MVN}/routines"
    if os.path.isdir(_r):
        for f in os.listdir(_r):
            if f.endswith(".m"):
                shutil.copy2(os.path.join(_r, f), f"{OUT}/opt/mvm/routines/{f}")
    for f in os.listdir(f"{MVN}/deploy/routines"):
        if f.endswith(".m"):
            shutil.copy2(f"{MVN}/deploy/routines/{f}", f"{OUT}/opt/mvm/routines/{f}")


            nr += 1
    print(f"  rutinas copiadas: {nr}")

    # helpers del rootfs (init + scripts .sh + configs), con @VERSION@ sustituido
    ver = open(f"{MVN}/lumenos/VERSION", encoding="utf-8").read().strip()
    for f in os.listdir(ROOTFS):
        s = os.path.join(ROOTFS, f)
        if not os.path.isfile(s):
            continue
        if f == "isolinux.cfg":
            continue
        d = f"{OUT}/etc/{f}" if f != "init" else f"{OUT}/init"
        data = open(s, "rb").read().replace(b"@VERSION@", b"v" + ver.encode())
        if (f == "init" or f.endswith(".sh") or f.endswith(".conf")
                or f.endswith(".script") or f.endswith(".m")
                or f.endswith(".cfg") or f.endswith(".EJEMPLO")):
            # CRLF -> LF: un \r en el shebang rompe la 1a linea ("sh\r: applet not found")
            data = data.replace(b"\r\n", b"\n")

        if f == "init":
            hook = (b"# --- LUMEN i686: precarga de dependencias (ver lumenos-preload.sh) ---\n"
                    b"if [ -f /etc/lumenos-preload.sh ]; then . /etc/lumenos-preload.sh; fi\n")
            marker = b"[hardware] cargando drivers base"
            i = data.find(marker)
            if i != -1:
                j = data.rfind(b"\n", 0, i) + 1
                data = data[:j] + hook + data[j:]
                print("  init: hook de preload inyectado")
            # ---- NOMBRE DEL NODO: de LA MAQUINA, no del seed ----
            chat = b'/opt/mvm/mvm-nas -p "$PDB" -r /opt/mvm/routines --chat'
            k = data.find(chat)
            if k != -1:
                w = data.rfind(b"while true; do", 0, k)
                if w != -1:
                    # ANTES del bucle: si va dentro se repetiria cada 5 s
                    data = data[:w] + NODO_BLOCK + TELNET_BLOCK + data[w:]
                    print("  init: NOMBRE DEL NODO + TELNET inyectados (antes del bucle)")
        open(d, "wb").write(data)
        # credenciales -> 0600 (hub.conf = clave HMAC del hub, wifi.conf = clave WiFi)
        if f in ("hub.conf", "wifi.conf"):
            modo = 0o600
        else:
            modo = 0o755 if (f == "init" or f.endswith(".sh") or f == "udhcpc.script") else 0o644
        os.chmod(d, modo)
    print(f"  raiz: init + {len(os.listdir(ROOTFS))-2} ficheros")
    copy_firmware()
    copy_wpa()
    copy_seed()
    copy_kbd()

    print("== empaquetando cpio-newc + gzip ==")
    out_gz = f"{B}/assets/initramfs-lumenos-i686.gz"
    pack_cpio_gz(OUT, out_gz)
    sz = os.path.getsize(out_gz)
    print(f"  initramfs-lumenos-i686.gz = {sz} bytes ({sz/1048576:.1f} MB)")


def pack_cpio_gz(root, out_path):
    """cpio newc + gzip, escrito a mano (no hay cpio en Windows)."""
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        rel = os.path.relpath(dirpath, root).replace("\\", "/")
        entries.append(("dir", rel, dirpath))
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            r = os.path.relpath(p, root).replace("\\", "/")
            entries.append(("file", r, p))

    def emit(raw, name, mode, data, ino, nlink=1):
        nm = name.encode() + b"\x00"
        hdr = b"070701"
        hdr += b"%08X" % ino
        hdr += b"%08X" % mode
        hdr += b"%08X" % 0          # uid
        hdr += b"%08X" % 0          # gid
        hdr += b"%08X" % nlink
        hdr += b"%08X" % 0          # mtime
        hdr += b"%08X" % len(data)
        hdr += b"%08X%08X" % (0, 0)  # devmajor devminor
        hdr += b"%08X%08X" % (0, 0)  # rdevmajor rdevminor
        hdr += b"%08X" % len(nm)
        hdr += b"%08X" % 0          # check
        raw.write(hdr)
        raw.write(nm)
        _t = 110 + len(nm)
        raw.write(b"\x00" * (((_t + 3) // 4) * 4 - _t))
        raw.write(data)
        raw.write(b"\x00" * ((4 - (len(data) % 4)) % 4))

    import io
    buf = io.BytesIO()
    ino = 1
    for kind, r, p in entries:
        ino += 1
        if kind == "dir":
            name = "." if r == "." else r
            emit(buf, name, 0o040755, b"", ino, nlink=2)
        else:
            st = os.lstat(p)
            if os.path.islink(p):
                emit(buf, r, 0o120777, os.readlink(p).encode(), ino)
            else:
                base = r.rsplit("/", 1)[-1]
                es_loader = base.startswith("ld-") or base.startswith("ld-linux")
                if r in ("etc/hub.conf", "etc/wifi.conf",
                         "opt/mvm/seed-local.m", "opt/mvm/serve.key"):
                    emit(buf, r, 0o100600, open(p, "rb").read(), ino)
                    continue
                mode = 0o100755 if (r == "init" or r.endswith(".sh")
                                    or r.startswith("bin/") or r.startswith("sbin/")
                                    or r.startswith("opt/mvm/") or es_loader
                                    or r.startswith("usr/sbin/") or r.startswith("usr/bin/")
                                    or r == "etc/udhcpc.script") else 0o100644
                emit(buf, r, mode, open(p, "rb").read(), ino)
    emit(buf, "TRAILER!!!", 0, b"", ino)
    with open(out_path, "wb") as f:
        f.write(gzip.compress(buf.getvalue(), 9))


if __name__ == "__main__":
    main()
