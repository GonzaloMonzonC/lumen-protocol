#!/usr/bin/env python3
"""Verifica el binario x86_64 desplegado: ELF64 x86-64, estatico, con los cambios."""
import os, struct, time

for f in ("mvm-nas-x86_64-musl", "mvm-nas-x86_64-musl.antes"):
    p = "C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/bin/" + f
    if not os.path.isfile(p):
        print(f"{f}: NO EXISTE")
        continue
    d = open(p, "rb").read()
    ph = struct.unpack_from("<Q", d, 32)[0]
    es = struct.unpack_from("<H", d, 54)[0]
    n = struct.unpack_from("<H", d, 56)[0]
    dino = any(struct.unpack_from("<I", d, ph + i * es)[0] == 3 for i in range(n))
    mach = struct.unpack_from("<H", d, 18)[0]
    print(f"{f}")
    print(f"   {len(d)} B · {time.strftime('%d %H:%M', time.localtime(os.path.getmtime(p)))}"
          f" · ELF{'64' if d[4] == 2 else '32'} · machine={mach} ({'x86-64' if mach == 62 else '?'})"
          f" · {'dinamico' if dino else 'ESTATICO'}")
    for t in (b"X-DDP-HMAC2", b"X-DDP-Node", b"ddp_hmac_key", b"prefix"):
        print(f"   {t.decode():<14} {'SI' if t in d else 'no'}")
