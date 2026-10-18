#!/usr/bin/env python3
"""El rlib real: liblumen_mlight.rlib — lleva el cambio de host.rs?"""
import os, time

d = "C:/Users/gonzalo/Documents/GitHub/mvm-nas/target/i686-unknown-linux-musl/release/deps"
for f in ("liblumen_mlight.rlib", "lumen_mlight.d"):
    p = os.path.join(d, f)
    if not os.path.isfile(p):
        continue
    b = open(p, "rb").read()
    print(f"{f}: {os.path.getsize(p)} B  modificado {time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(p)))}")
    if f.endswith(".rlib"):
        for tok in (b"nodo_id", b"ddp_hmac_key", b"X-DDP-HMAC2", b"X-DDP-Node"):
            print(f"    {tok.decode():<14} {'SI' if tok in b else 'no'}")
