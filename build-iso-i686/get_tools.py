#!/usr/bin/env python3
"""PUNTO 1: meter iwconfig / iwlist / rfkill en el ISO (sin Docker, Python directo).

Descarga los .deb i386 de Debian, extrae los binarios y los deja en extra-bin/.
Un .deb es un archivo 'ar' con data.tar.zst/xz dentro: se parsea a mano.
"""
import io
import lzma
import re
import subprocess
import tarfile
import urllib.request
from pathlib import Path

EXTRA = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/extra-bin")
EXTRA.mkdir(exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (LumenOS build)"}

PAQUETES = {
    "wireless-tools": "https://deb.debian.org/debian/pool/main/w/wireless-tools/",
    "rfkill": "https://deb.debian.org/debian/pool/main/r/rfkill/",
}


def busca_deb(url):
    """Del indice del pool, coge el .deb i386 mas nuevo."""
    html = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8", "replace")
    debs = re.findall(r'href="([^"]+_i386\.deb)"', html)
    if not debs:
        return None
    debs.sort()
    return url + debs[-1]


def ar_miembros(blob):
    """Un .deb es 'ar': devuelve [(nombre, bytes)]."""
    assert blob[:8] == b"!<arch>\n", "no es un archivo ar"
    i, out = 8, []
    while i + 60 <= len(blob):
        hdr = blob[i:i + 60]
        nombre = hdr[:16].decode("ascii", "replace").strip()
        try:
            tam = int(hdr[48:58].decode("ascii").strip())
        except ValueError:
            break
        datos = blob[i + 60:i + 60 + tam]
        out.append((nombre, datos))
        i += 60 + tam + (tam % 2)
    return out


def saca_binarios(deb_url, nombres):
    blob = urllib.request.urlopen(urllib.request.Request(deb_url, headers=UA), timeout=60).read()
    for nombre, datos in ar_miembros(blob):
        if not nombre.startswith("data.tar"):
            continue
        if nombre.endswith(".zst"):
            print("   (data.tar.zst: necesito zstd; probando otra via)")
            return []
        if nombre.endswith(".xz"):
            datos = lzma.decompress(datos)
        elif nombre.endswith(".gz"):
            import gzip
            datos = gzip.decompress(datos)
        tf = tarfile.open(fileobj=io.BytesIO(datos))
        sacados = []
        for m in tf.getmembers():
            base = m.name.rsplit("/", 1)[-1]
            if base in nombres and m.isfile():
                f = tf.extractfile(m)
                if f:
                    (EXTRA / base).write_bytes(f.read())
                    sacados.append(base)
        return sacados
    return []


total = []
for paquete, url in PAQUETES.items():
    print(f"[{paquete}]")
    d = busca_deb(url)
    if not d:
        print("   X no encontre .deb i386")
        continue
    print("   deb:", d.rsplit("/", 1)[-1])
    n = saca_binarios(d, {"iwconfig", "iwlist", "rfkill", "iwgetid", "ifrename"})
    print("   binarios:", n or "(ninguno)")
    total += n

print("\nen extra-bin/:", sorted(p.name for p in EXTRA.iterdir()))
