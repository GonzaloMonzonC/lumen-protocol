#!/usr/bin/env python3
"""Anade loadkeys (i386) + mapas de teclado es/uk/de/fr/it/pt al initramfs.
El init hace: [ -x /bin/loadkeys ] && /bin/loadkeys /etc/keymaps/$TECLADO.map.gz
loadkeys es glibc (del paquete kbd), no applet de busybox."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

anchor = "def copy_seed():"
new = '''KBD_ROOT = f"{B}/assets/kbd-root"
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
    aviso = "OK mapa ESPANOL dentro" if os.path.exists(f"{OUT}/etc/keymaps/es.map.gz") \\
        else "!! FALTA es.map.gz"
    print(f"  loadkeys + {nm} mapas de teclado ({nuevas} libs nuevas) · {aviso}")


'''
assert anchor in s, "no encontre copy_seed"
s = s.replace(anchor, new + anchor, 1)

old = "    copy_wpa()\n    copy_seed()"
new2 = "    copy_wpa()\n    copy_seed()\n    copy_kbd()"
assert old in s, "no encontre las llamadas"
s = s.replace(old, new2, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
import py_compile
py_compile.compile(P, doraise=True)
print("PATCH OK y compila")
