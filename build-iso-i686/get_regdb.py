#!/usr/bin/env python3
"""regulatory.db -> /lib/firmware/ en el ISO.
El kernel lo pide ('cfg80211: failed to load regulatory.db') y sin el arranca en
dominio CORE, que puede impedir instalar la clave del WPA (el fallo que vemos)."""
import io, lzma, re, shutil, subprocess, tarfile, urllib.request, zlib
from pathlib import Path

B = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686")
EXTRA = B / "extra-bin"
UA = {"User-Agent": "Mozilla/5.0 (LumenOS build)"}


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


url = "https://deb.debian.org/debian/pool/main/w/wireless-regdb/"
html = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8", "replace")
debs = sorted(re.findall(r'href="(wireless-regdb_[^"]+_all\.deb)"', html))
print("candidatos:", debs[-3:])
if not debs:
    raise SystemExit("no encontre el .deb")
blob = urllib.request.urlopen(urllib.request.Request(url + debs[-1], headers=UA), timeout=60).read()
print("deb:", debs[-1], len(blob), "bytes")
sacados = []
for nombre, datos in ar_miembros(blob):
    if not nombre.startswith("data.tar"):
        continue
    if nombre.endswith(".xz"):
        datos = lzma.decompress(datos)
    elif nombre.endswith(".gz"):
        import gzip
        datos = gzip.decompress(datos)
    elif nombre.endswith(".zst"):
        print("  (data.tar.zst; intento zstd)")
        import subprocess as sp
        datos = sp.run(["zstd", "-d", "-c"], input=datos, capture_output=True).stdout
        if not datos:
            print("  X sin zstd: no puedo")
            continue
    tf = tarfile.open(fileobj=io.BytesIO(datos))
    for m in tf.getmembers():
        base = m.name.rsplit("/", 1)[-1]
        if base.startswith("regulatory.db") and m.isfile():
            f = tf.extractfile(m)
            if f:
                (EXTRA / base).write_bytes(f.read())
                sacados.append(base)
    break
print("extraidos:", sacados, "· ERR" if not sacados else "OK")

# el build: regulatory.db* -> /lib/firmware/
P = B / "build_initramfs_i686.py"
s = open(P, encoding="utf-8", newline="").read()
if "firmware" not in s or "regulatory" not in s:
    old = '''            dest = f"{OUT}/lib/{f}" if ".so" in f else f"{OUT}/bin/{f}"'''
    new = '''            # regulatory.db -> /lib/firmware/ (cfg80211 lo pide al arrancar;
            # sin el, el kernel arranca en dominio CORE y puede no instalar la
            # clave del WPA: 'Failed to set PTK to the driver' en el Asus)
            if f.startswith("regulatory.db"):
                os.makedirs(f"{OUT}/lib/firmware", exist_ok=True)
                shutil.copy2(os.path.join(_eb, f), f"{OUT}/lib/firmware/{f}")
                os.chmod(f"{OUT}/lib/firmware/{f}", 0o644)
                continue
            dest = f"{OUT}/lib/{f}" if ".so" in f else f"{OUT}/bin/{f}"'''
    assert old in s, "no encontre el bloque dest"
    s = s.replace(old, new, 1)
    open(P, "w", encoding="utf-8", newline="").write(s)
    print("build OK: regulatory.db -> /lib/firmware/")
