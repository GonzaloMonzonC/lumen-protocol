#!/usr/bin/env python3
"""FIX FINAL: meter los modulos de cripto en modules.dep y modules.alias.
El .ko estaba pero modprobe no lo veia (modules.dep lo ignora) -> no se cargaba
-> mac80211 sin CCMP -> 'key addition failed'."""
import glob
import os
from pathlib import Path

B = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686")
INI = B / "initramfs-i686"

mods = glob.glob(str(INI / "lib/modules/*"))
if not mods:
    raise SystemExit("no hay lib/modules en el initramfs")
MOD = mods[0]
print("dir de modulos:", MOD)

CRIPTO = ["ccm", "ctr", "gcm", "ghash-generic", "ecb", "cbc", "crc32c_generic",
          "arc4", "cmac", "aes_ti"]

# --- modules.dep:  kernel/crypto/<x>.ko:<deps>
dep = os.path.join(MOD, "modules.dep")
lineas = open(dep, encoding="utf-8", errors="replace").read().split("\n") if os.path.exists(dep) else []
ya = {l.split(":")[0] for l in lineas if ":" in l}
nuevas = []
for m in CRIPTO:
    rel = f"kernel/crypto/{m}.ko"
    if os.path.exists(os.path.join(MOD, rel)) and rel not in ya:
        nuevas.append(f"{rel}:")
# deps reales de algunos
lineas = [l for l in lineas if l.strip()]
lineas += nuevas
open(dep, "w", encoding="utf-8", newline="\n").write("\n".join(lineas) + "\n")
print(f"modules.dep: +{len(nuevas)} lineas de cripto")

# --- modules.alias:  alias crypto-<algo> <mod>   (ASI pide el kernel el modulo)
alias = os.path.join(MOD, "modules.alias")
al = open(alias, encoding="utf-8", errors="replace").read().split("\n") if os.path.exists(alias) else []
nuevos_al = []
mapa = {
    "ccm": ["crypto-ccm", "ccm(aes)"],
    "ctr": ["crypto-ctr"],
    "gcm": ["crypto-gcm"],
    "ghash-generic": ["crypto-ghash"],
    "ecb": ["crypto-ecb"],
    "cbc": ["crypto-cbc"],
    "crc32c_generic": ["crypto-crc32c"],
    "arc4": ["crypto-arc4"],
    "cmac": ["crypto-cmac"],
    "aes_ti": ["crypto-aes"],
}
for m, als in mapa.items():
    if not os.path.exists(os.path.join(MOD, f"kernel/crypto/{m}.ko")):
        continue
    for a in als:
        linea = f"alias {a} {m}"
        if not any(l.strip() == linea for l in al):
            nuevos_al.append(linea)
al = [l for l in al if l.strip()] + nuevos_al
open(alias, "w", encoding="utf-8", newline="\n").write("\n".join(al) + "\n")
print(f"modules.alias: +{len(nuevos_al)} alias (crypto-ccm -> ccm, etc)")
