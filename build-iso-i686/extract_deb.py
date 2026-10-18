#!/usr/bin/env python3
"""Extrae .deb (ar) soportando data.tar.xz/.gz/.zst -> destino."""
import sys, os, io, tarfile, shutil, subprocess


def ar_entries(path):
    with open(path, "rb") as f:
        if f.read(8) != b"!<arch>\n":
            raise SystemExit("no es ar")
        while True:
            hdr = f.read(60)
            if len(hdr) < 60:
                break
            name = hdr[0:16].decode("ascii", "replace").strip()
            size = int(hdr[48:58].decode("ascii").strip())
            data = f.read(size)
            if size % 2:
                f.read(1)
            yield name, data


def decompress(base, data):
    if base.endswith(".xz"):
        import lzma
        return lzma.decompress(data)
    if base.endswith(".gz"):
        import gzip
        return gzip.decompress(data)
    if base.endswith(".zst"):
        try:
            import zstandard
            return zstandard.ZstdDecompressor().decompress(data, max_output_size=2 << 30)
        except ImportError:
            pass
        zst = shutil.which("zstd") or shutil.which("unzstd")
        if not zst:
            raise SystemExit("necesito zstd (binario o modulo python zstandard)")
        p = subprocess.run([zst, "-d", "-c"], input=data, capture_output=True)
        if p.returncode != 0:
            raise SystemExit("zstd fallo: " + p.stderr.decode("utf-8", "replace"))
        return p.stdout
    raise SystemExit("compresion no soportada: " + base)


def main(deb, outdir):
    os.makedirs(outdir, exist_ok=True)
    for name, data in ar_entries(deb):
        base = name.rstrip("/")
        if base.startswith("data.tar"):
            print("miembro:", base, len(data), "bytes")
            raw = decompress(base, data)
            tarfile.open(fileobj=io.BytesIO(raw), mode="r:").extractall(outdir)
            print("extraido en:", outdir)
            return
    raise SystemExit("sin data.tar.*")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
