#!/usr/bin/env python3
"""Aplica los 3 arreglos a build_initramfs_i686.py:
   1) + b44 (Broadcom 440x) y + firmware WiFi (ipw2200/iwl3945/ath9k_htc)
   2) precarga ORDENADA de dependencias (/etc/lumenos-preload.sh)
   3) inyeccion del preload en NUESTRA copia del init (antes del bucle de drivers)
"""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()
orig = s

# ---------- 1) anadir b44 a la lista de NICs ----------
old_nic = "8139too 8139cp sky2 tg3 via-rhine sis900 forcedeth e100 e1000 e1000e r8169"
new_nic = "8139too 8139cp sky2 tg3 via-rhine sis900 forcedeth e100 e1000 e1000e r8169 b44"
assert old_nic in s, "no encontre la linea de NICs"
s = s.replace(old_nic, new_nic)

# ---------- 2) firmware curado + preload: nuevas funciones ----------
anchor = "def copy_tree():"
new_funcs = '''FW_DIR = f"{B}/assets/fw-root/lib/firmware"
FW_FILES = [
    "ipw2200-bss.fw", "ipw2200-ibss.fw", "ipw2200-sniffer.fw",
    "iwlwifi-3945-2.ucode",
    "ath9k_htc/htc_7010.fw", "ath9k_htc/htc_9271.fw",
]


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
            "for m in " + " ".join(preload) + "; do modprobe \\"$m\\" 2>/dev/null; done",
            ""]
    with open(f"{OUT}/etc/lumenos-preload.sh", "w", newline="\\n") as f:
        f.write("\\n".join(body))
    os.chmod(f"{OUT}/etc/lumenos-preload.sh", 0o755)
    print(f"  preload: {len(preload)} dependencias en orden topologico")
    print("   " + " ".join(preload[:12]) + (" ..." if len(preload) > 12 else ""))


'''
assert anchor in s, "no encontre copy_tree"
s = s.replace(anchor, new_funcs + anchor, 1)

# ---------- 3) llamadas en main() + inyeccion en el init ----------
old_call = '''    print("== piezas del sistema ==")'''
new_call = '''    write_preload(need, idx)
    print("== piezas del sistema ==")'''
assert old_call in s, "no encontre '== piezas del sistema =='"
s = s.replace(old_call, new_call, 1)

old_fw = '''    print(f"  raiz: init + {len(os.listdir(ROOTFS))-2} ficheros")'''
new_fw = old_fw + '''
    copy_firmware()'''
assert old_fw in s, "no encontre el print de la raiz"
s = s.replace(old_fw, new_fw, 1)

# inyeccion en el init: sourcear el preload antes del bucle de drivers
old_ini = '''        data = open(s, "rb").read().replace(b"@VERSION@", b"v" + ver.encode())'''
new_ini = '''        data = open(s, "rb").read().replace(b"@VERSION@", b"v" + ver.encode())
        if f == "init":
            hook = (b"# --- LUMEN i686: precarga de dependencias (ver lumenos-preload.sh) ---\\n"
                    b"if [ -f /etc/lumenos-preload.sh ]; then . /etc/lumenos-preload.sh; fi\\n")
            marker = b"[hardware] cargando drivers base"
            i = data.find(marker)
            if i != -1:
                j = data.rfind(b"\\n", 0, i) + 1
                data = data[:j] + hook + data[j:]
                print("  init: hook de preload inyectado")'''
assert old_ini in s, "no encontre la lectura del init"
s = s.replace(old_ini, new_ini, 1)

open(P, "w", encoding="utf-8", newline="").write(s)
print("PATCH OK:", len(orig), "->", len(s), "bytes")
