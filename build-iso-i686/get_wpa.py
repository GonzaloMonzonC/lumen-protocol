#!/usr/bin/env python3
"""Descarga wpa_supplicant (i386) + sus dependencias desde Debian y las extrae."""
import gzip, io, os, subprocess, sys

ASSETS = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/assets"
DEST = f"{ASSETS}/wpa-root"
BASE = "https://deb.debian.org/debian"

PAQUETES = [
    "wpasupplicant",
    "libnl-3-200",
    "libnl-genl-3-200",
    "libnl-route-3-200",
    "libssl3",
    "libc6",
    "libdbus-1-3",
    "libpcsclite1",
    "libsystemd0",
    "libreadline8",
    "libtinfo6",
    "libcap2",
    "libgcrypt20",
    "liblz4-1",
    "liblzma5",
    "libzstd1",
    "libgpg-error0",
]

print("== indice i386 de bookworm ==")
idx = subprocess.run(["curl", "-s", f"{BASE}/dists/bookworm/main/binary-i386/Packages.gz"],
                     capture_output=True).stdout
txt = gzip.decompress(idx).decode("utf-8", "replace")

# parse: Package -> (Version, Filename)
want = {p: None for p in PAQUETES}
cur = {}
for line in txt.splitlines():
    if line.startswith("Package: "):
        cur = {"name": line[9:].strip()}
    elif line.startswith("Filename: ") and cur.get("name") in want:
        want[cur["name"]] = line[10:].strip()
    elif not line.strip():
        cur = {}

os.makedirs(DEST, exist_ok=True)
for p in PAQUETES:
    fn = want[p]
    if not fn:
        print(f"  !! {p}: NO ENCONTRADO en el indice")
        continue
    deb = f"{ASSETS}/{p}.deb"
    if not os.path.isfile(deb):
        subprocess.run(["curl", "-sL", "-o", deb, f"{BASE}/{fn}"], check=False)
    print(f"  {p}: {fn.split('/')[-1]}  ({os.path.getsize(deb)//1024 if os.path.isfile(deb) else 0} KB)")
    sys.path.insert(0, "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686")
    from extract_deb import main as ex
    ex(deb, DEST)

print("\n== binario y librerias extraidas ==")
for root, _, files in os.walk(DEST):
    for f in files:
        if f.startswith("wpa_supplicant") and "cli" not in f:
            print("  BIN", os.path.join(root, f).replace(DEST, ""))
libs = []
for root, _, files in os.walk(DEST):
    for f in files:
        if ".so" in f:
            libs.append(os.path.join(root, f).replace(DEST, ""))
print(f"  librerias: {len(libs)}")
for l in sorted(libs)[:14]:
    print("   ", l)
