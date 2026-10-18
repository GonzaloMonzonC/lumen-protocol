#!/usr/bin/env python3
"""Analiza compatibilidad: config del kernel (PAE/nivel CPU) + modulos presentes."""
import gzip, os

A = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686"
CFG = f"{A}/assets/kernel-root/boot/config-6.1.0-50-686"
INITRD = f"{A}/assets/initramfs-lumenos-i686.gz"

print("=== 1. CONFIG DEL KERNEL (nivel de CPU y PAE) ===")
want = ["CONFIG_X86_PAE", "CONFIG_M486", "CONFIG_M586", "CONFIG_M686",
        "CONFIG_M686_PAE", "CONFIG_X86_32", "CONFIG_SMP", "CONFIG_HIGHMEM4G",
        "CONFIG_HIGHMEM64G", "CONFIG_FB_VESA", "CONFIG_DRM_I915", "CONFIG_FB",
        "CONFIG_VT", "CONFIG_FRAMEBUFFER_CONSOLE"]
cfg = {}
for line in open(CFG, encoding="utf-8", errors="replace"):
    if line.startswith("CONFIG_") and "=" in line:
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip()
for w in want:
    if w in cfg:
        print(f"  {w}={cfg[w]}")
    else:
        print(f"  {w}=<no presente / no definido>")

# CPU family: mostrar los CONFIG_M* de CPU activos
print("\n  CPUs marcadas (=y) en el config:")
for k, v in cfg.items():
    if k.startswith("CONFIG_M") and v == "y" and "CPU" not in k and "_" not in k[8:]:
        print(f"    {k}")

print("\n=== 2. MODULOS PRESENTES EN EL INITRAMFS ===")
raw = gzip.decompress(open(INITRD, "rb").read())


def a4(x):
    return (x + 3) & ~3


pos, names = 0, set()
while pos + 110 <= len(raw) and raw[pos:pos+6] == b"070701":
    size = int(raw[pos+54:pos+62], 16)
    nsz = int(raw[pos+94:pos+102], 16)
    nm = raw[pos+110:pos+110 + nsz - 1].decode("utf-8", "replace")
    d0 = pos + a4(110 + nsz)
    names.add(os.path.basename(nm))
    pos = d0 + a4(size)
    if nm == "TRAILER!!!":
        break

# (modulo, para que maquina)
check = [
    ("8139too", "red Realtek 8139 (muy comun 1999-2005)"),
    ("e100", "red Intel PRO/100 (portatiles 2003-2006)"),
    ("e1000", "red Intel PRO/1000"),
    ("b44", "red Broadcom 440x (MUCHOS Acer TravelMate)"),
    ("tg3", "red Broadcom gigabit"),
    ("sky2", "red Marvell"),
    ("forcedeth", "red nVidia"),
    ("sis900", "red SiS"),
    ("via-rhine", "red VIA"),
    ("r8169", "red Realtek gigabit"),
    ("atl1c", "red Atheros L1C (ASUS Eee PC 1005HA)"),
    ("atl1e", "red Atheros L1E"),
    ("ata_piix", "disco IDE/PATA (TravelMate)"),
    ("piix", "disco IDE legacy"),
    ("libata", "capa SATA/PATA"),
    ("ahci", "disco SATA"),
    ("i915", "video Intel (GMA 950 del Eee PC / 855 del TravelMate)"),
    ("drm_buddy", "dep de i915"),
    ("ttm", "dep de i915"),
    ("simpledrm", "framebuffer generico"),
    ("ath9k", "WiFi Atheros 802.11n (Eee PC 1005HA)"),
    ("ath9k_common", "dep de ath9k"),
    ("ath5k", "WiFi Atheros 802.11g"),
    ("ipw2200", "WiFi Intel PRO/Wireless 2200 (TravelMate)"),
    ("iwl3945", "WiFi Intel 3945"),
    ("ssb", "bus Broadcom"),
    ("b43", "WiFi Broadcom"),
    ("pcmcia", "PC Card (portatiles antiguos)"),
]
for mod, why in check:
    hit = [n for n in names if n == mod + ".ko"]
    print(f"  {'SI' if hit else 'NO'}  {mod:<14} {why}")

print(f"\n  total .ko: {sum(1 for n in names if n.endswith('.ko'))}")
