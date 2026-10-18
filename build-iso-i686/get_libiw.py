#!/usr/bin/env python3
"""Trae libiw.so (paquete libiw30) y ajusta el build: .so -> /lib, binarios -> /bin.
Sin esto iwconfig/iwlist no arrancan ('libiw.so not found')."""
import io, lzma, re, tarfile, urllib.request
from pathlib import Path

EXTRA = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/extra-bin")
UA = {"User-Agent": "Mozilla/5.0 (LumenOS build)"}


def ar_miembros(blob):
    assert blob[:8] == b"!<arch>\n"
    i, out = 8, []
    while i + 60 <= len(blob):
        hdr = blob[i:i + 60]
        nombre = hdr[:16].decode("ascii", "replace").strip()
        try:
            tam = int(hdr[48:58].decode("ascii").strip())
        except ValueError:
            break
        out.append((nombre, blob[i + 60:i + 60 + tam]))
        i += 60 + tam + (tam % 2)
    return out


url = "https://deb.debian.org/debian/pool/main/w/wireless-tools/"
html = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8", "replace")
debs = sorted(re.findall(r'href="(libiw30_[^"]+_i386\.deb)"', html))
print("candidatos libiw30:", debs[-3:])
if debs:
    blob = urllib.request.urlopen(urllib.request.Request(url + debs[-1], headers=UA), timeout=60).read()
    for nombre, datos in ar_miembros(blob):
        if nombre.startswith("data.tar"):
            if nombre.endswith(".xz"):
                datos = lzma.decompress(datos)
            elif nombre.endswith(".gz"):
                import gzip; datos = gzip.decompress(datos)
            tf = tarfile.open(fileobj=io.BytesIO(datos))
            for m in tf.getmembers():
                base = m.name.rsplit("/", 1)[-1]
                if base.startswith("libiw.so") and m.isfile():
                    f = tf.extractfile(m)
                    if f:
                        (EXTRA / base).write_bytes(f.read())
                        print("  extraido:", base)
            break

print("\nextra-bin ahora:", sorted(p.name for p in EXTRA.iterdir()))

# ── el build: .so -> /lib, resto -> /bin ──
P = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py")
s = open(P, encoding="utf-8", newline="").read()
old = '''    if os.path.isdir(_eb):
        os.makedirs(f"{OUT}/bin", exist_ok=True)
        for f in os.listdir(_eb):
            shutil.copy2(os.path.join(_eb, f), f"{OUT}/bin/{f}")
            os.chmod(f"{OUT}/bin/{f}", 0o755)
        print(f"  herramientas extra: {sorted(os.listdir(_eb))}")'''
new = '''    if os.path.isdir(_eb):
        os.makedirs(f"{OUT}/bin", exist_ok=True)
        os.makedirs(f"{OUT}/lib", exist_ok=True)
        for f in os.listdir(_eb):
            # las .so van a /lib (el cargador no busca en /bin); el resto a /bin
            dest = f"{OUT}/lib/{f}" if ".so" in f else f"{OUT}/bin/{f}"
            shutil.copy2(os.path.join(_eb, f), dest)
            os.chmod(dest, 0o755)
        print(f"  herramientas extra: {sorted(os.listdir(_eb))}")'''
assert old in s, "no encontre el bloque extra-bin"
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
print("build OK: .so -> /lib, binarios -> /bin")
