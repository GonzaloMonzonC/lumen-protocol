#!/usr/bin/env python3
"""La ISO x86-64 nueva lleva TODO? (hw, %WIFI, deteccion WiFi, paso 3, opcion B)"""
import gzip, io

import pycdlib

ISO = "C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/build/lumenos-v0.1.25.iso"
iso = pycdlib.PyCdlib()
iso.open(ISO)
buf = io.BytesIO()
iso.get_file_from_iso_fp(buf, rr_path="/initramfs-lumenos.gz")
blob = gzip.GzipFile(fileobj=io.BytesIO(buf.getvalue())).read()
print(f"initramfs descomprimido: {len(blob)} bytes")

marcas = [
    (b"Unknown HW action", "modulo hw (hw:* devices)"),
    (b"WDRVCONOCIDO", "deteccion WiFi pre-mac80211"),
    (b"rfkill unblock", "rfkill"),
    (b"%WIFI.m", "rutina %WIFI"),
    (b"%NM.m", "rutina %NM (paso 3)"),
    (b"%NR.m", "rutina %NR (paso 1)"),
    (b"mem_creada", "memoria aplanada"),
    (b"X-DDP-HMAC2", "firma con identidad"),
    (b"[ddp] nodo configurado", "config DDP en el init"),
]
for m, q in marcas:
    print(f"  {q:<34} {'SI' if m in blob else 'NO'}")
iso.close()
