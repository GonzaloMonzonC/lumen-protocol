#!/usr/bin/env python3
"""Verifica el binario empaquetado en el initramfs i686 (modulo hw + tamaño)."""
import os
import struct

P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/initramfs-i686/opt/mvm/mvm-nas"
d = open(P, "rb").read()
print("tamaño empaquetado:", len(d), "(esperado 4645592)")
print("ELF32:", d[:4] == b"\x7fELF" and d[4] == 1, "i386:", struct.unpack_from("<H", d, 18)[0] == 3)
antes = os.path.getsize(
    "C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/bin/mvm-nas-i686-musl.antes-opcionB")
print("(referencia del binario VIEJO:", antes, "bytes)")

for marca in (b"Unknown HW action", b"sin rfkill", b"sin bateria", b"hw:net",
              b"X-DDP-HMAC2", b"X-DDP-Node"):
    print(f"  {marca.decode():<20} {'SI' if marca in d else 'no'}")
