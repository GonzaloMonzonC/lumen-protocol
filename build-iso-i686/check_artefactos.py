#!/usr/bin/env python3
"""Busca los artefactos de lumen-m-light y comprueba si llevan 'nodo_id'."""
import glob, os, time

T = "C:/Users/gonzalo/Documents/GitHub/mvm-nas/target/i686-unknown-linux-musl"
arts = []
for pat in ("**/liblumen_m_light*.rlib", "**/liblumen_m_light*.rmeta"):
    arts += glob.glob(os.path.join(T, pat), recursive=True)
print(f"artefactos de lumen_m_light: {len(arts)}")
for a in arts[:6]:
    d = open(a, "rb").read()
    print(f"  {os.path.getsize(a):>9} B  {time.strftime('%H:%M', time.localtime(os.path.getmtime(a)))}"
          f"  nodo_id={'SI' if b'nodo_id' in d else 'no'}"
          f"  ddp_hmac_key={'SI' if b'ddp_hmac_key' in d else 'no'}"
          f"  {os.path.basename(a)[:46]}")

h = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/rust/lumen-m-light/src/host.rs"
print(f"\nhost.rs modificado: {time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(h)))}")
src = open(h, encoding="utf-8").read()
print(f"host.rs contiene 'nodo_id': {'SI' if 'nodo_id' in src else 'NO'}")
