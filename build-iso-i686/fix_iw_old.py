#!/usr/bin/env python3
"""2a: traer un wireless-tools ANTIGUO (el que metí pedia GLIBC_2.38 y el nodo
lleva una mas vieja). Se coge el de bullseye (glibc 2.31), no el mas nuevo."""
import io, lzma, re, urllib.request
from pathlib import Path

EXTRA = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/extra-bin")
UA = {"User-Agent": "Mozilla/5.0 (LumenOS build)"}
URL = "https://deb.debian.org/debian/pool/main/w/wireless-tools/"


def ar_miembros(blob):
    assert blob[:8] == b"!<arch>\n"
    i, out = 8, []
    while i + 60 <= len(blob):
        h = blob[i:i + 60]
        n = h[:16].decode("ascii", "replace").strip()
        try:
            t = int(h[48:58].decode("ascii").strip())
        except ValueError:
            break
        out.append((n, blob[i + 60:i + 60 + t]))
        i += 60 + t + (t % 2)
    return out


html = urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=30).read().decode("utf-8", "replace")
cands = sorted(re.findall(r'href="(wireless-tools_[^"]+_i386\.deb)"', html))
print("candidatos:")
for c in cands:
    print("   ", c)

# el MAS ANTIGUO de la lista (el moderno pide GLIBC 2.38 y el nodo no llega)
elegido = cands[0]
print("\nelegido (el mas antiguo):", elegido)

blob = urllib.request.urlopen(urllib.request.Request(URL + elegido, headers=UA), timeout=60).read()
sacados = []
for nombre, datos in ar_miembros(blob):
    if not nombre.startswith("data.tar"):
        continue
    if nombre.endswith(".xz"):
        datos = lzma.decompress(datos)
    elif nombre.endswith(".gz"):
        import gzip
        datos = gzip.decompress(datos)
    import tarfile
    tf = tarfile.open(fileobj=io.BytesIO(datos))
    for m in tf.getmembers():
        base = m.name.rsplit("/", 1)[-1]
        if base in ("iwconfig", "iwlist", "iwgetid") and m.isfile():
            f = tf.extractfile(m)
            if f:
                (EXTRA / base).write_bytes(f.read())
                sacados.append(base)
    break
print("reemplazados:", sacados)
print("extra-bin:", sorted(p.name for p in EXTRA.iterdir()))
