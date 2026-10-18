#!/usr/bin/env python3
"""CIERRA LA WIFI: meter los modulos de CRIPTO en el initramfs.
Sin aes/ccm, mac80211 no puede instalar la clave CCMP -> key addition failed ->
falla igual en TODOS los PCs."""
import shutil
from pathlib import Path

B = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686")
ASSETS = B / "assets"
INI = B / "initramfs-i686"

# 1) donde estan los .ko de cripto en el kernel extraido?
candidatos = list(ASSETS.glob("*/lib/modules/*/kernel/crypto"))
print("dirs de cripto encontrados:", [str(c) for c in candidatos][:3])
if not candidatos:
    raise SystemExit("no encontre el dir crypto/ del kernel")

CRYPTO = candidatos[0]
quiero = ["aes_generic.ko", "aes-i586.ko", "aes.ko", "ccm.ko", "ctr.ko",
          "gcm.ko", "crc32c.ko", "crc32c-intel.ko", "ghash-generic.ko",
          "arc4.ko", "ecb.ko", "cbc.ko", "libaes.ko"]
disponibles = {p.name: p for p in CRYPTO.glob("*.ko")}
print("disponibles en crypto/:", sorted(disponibles)[:26])

# 2) a donde van en el initramfs
moddirs = list(INI.glob("lib/modules/*"))
print("modulo dir en el initramfs:", [str(m) for m in moddirs])
if not moddirs:
    raise SystemExit("no hay lib/modules en el initramfs")
MOD = moddirs[0]
dest = MOD / "kernel" / "crypto"
dest.mkdir(parents=True, exist_ok=True)

copiados = []
for n in quiero:
    if n in disponibles:
        shutil.copy2(disponibles[n], dest / n)
        copiados.append(n)
print("\nCOPIADOS al initramfs:", copiados)
print("no estaban:", [n for n in quiero if n not in disponibles and n != "aes.ko"])
