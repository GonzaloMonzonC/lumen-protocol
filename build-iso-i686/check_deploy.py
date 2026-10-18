#!/usr/bin/env python3
"""Comprueba el binario desplegado + el respaldo."""
import os, struct, time

B = "C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/bin"
for f in ("mvm-nas-i686-musl", "mvm-nas-i686-musl.antes-opcionB"):
    p = os.path.join(B, f)
    if not os.path.isfile(p):
        print(f"{f}: NO EXISTE")
        continue
    d = open(p, "rb").read()
    ph = struct.unpack_from("<I", d, 28)[0]
    n = struct.unpack_from("<H", d, 44)[0]
    es = struct.unpack_from("<H", d, 42)[0]
    dino = any(struct.unpack_from("<I", d, ph + i * es)[0] == 3 for i in range(n))
    print(f"{f}")
    print(f"   {len(d)} B · {time.strftime('%d %H:%M', time.localtime(os.path.getmtime(p)))}"
          f" · ELF{'32' if d[4] == 1 else '64'}"
          f" · machine={struct.unpack_from('<H', d, 18)[0]}"
          f" · {'dinamico' if dino else 'ESTATICO'}")
    for t in (b"X-DDP-HMAC2", b"X-DDP-Node", b"ddp_hmac_key"):
        print(f"   {t.decode():<14} {'SI' if t in d else 'no'}")
