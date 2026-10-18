#!/usr/bin/env python3
"""Verifica el binario recien construido: ELF32 i386, estatico, con las funciones nuevas."""
import struct

P = "C:/Users/gonzalo/Documents/GitHub/mvm-nas/target/i686-unknown-linux-musl/release/mvm-nas"
d = open(P, "rb").read()
print(f"tamano: {len(d)} bytes")
print(f"magic : {d[:4]!r}  clase={'32' if d[4]==1 else '64'}  endian={d[5]}")
e_type = struct.unpack_from("<H", d, 16)[0]
e_machine = struct.unpack_from("<H", d, 18)[0]
print(f"e_type={e_type} ({'ET_EXEC' if e_type==2 else 'ET_DYN' if e_type==3 else '?'})  "
      f"e_machine={e_machine} ({'i386' if e_machine==3 else '?'})")

# interpreter (PT_INTERP) -> si NO hay, es estatico
phoff = struct.unpack_from("<I", d, 28)[0]
phes = struct.unpack_from("<H", d, 42)[0]
phnum = struct.unpack_from("<H", d, 44)[0]
interp = None
for i in range(phnum):
    o = phoff + i * phes
    t = struct.unpack_from("<I", d, o)[0]
    if t == 3:
        po = struct.unpack_from("<I", d, o + 4)[0]
        interp = d[po:d.index(b"\x00", po)].decode()
print(f"PT_INTERP: {interp!r}  ->  {'ESTATICO' if interp is None else 'dinamico'}")

# las funciones nuevas tienen que estar
for s in (b"X-DDP-HMAC2", b"X-DDP-Node"):
    print(f"  contiene {s.decode()}: {'SI' if s in d else 'NO'}")
print(f"  contiene ddp_hmac_key: {'SI' if b'ddp_hmac_key' in d else 'NO'}")
print(f"  contiene nodo_id: {'SI' if b'nodo_id' in d else 'NO'}")
