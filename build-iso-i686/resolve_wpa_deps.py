#!/usr/bin/env python3
"""Resuelve el cierre COMPLETO de DT_NEEDED de wpa_supplicant/wpa_cli.
Lee los ELF de 32 bits directamente (sin ldd) y dice que falta."""
import os, struct, sys

WR = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/assets/wpa-root"
BUSQ = [f"{WR}/lib/i386-linux-gnu", f"{WR}/usr/lib/i386-linux-gnu",
        f"{WR}/lib", f"{WR}/usr/lib"]


def elf_info(path):
    """devuelve (interp, [DT_NEEDED...]) de un ELF 32-bit"""
    d = open(path, "rb").read()
    if d[:4] != b"\x7fELF" or d[4] != 1:
        return None, []
    e_phoff = struct.unpack_from("<I", d, 28)[0]
    e_phentsize = struct.unpack_from("<H", d, 42)[0]
    e_phnum = struct.unpack_from("<H", d, 44)[0]
    interp, dyn, loads = None, None, []
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        p_type = struct.unpack_from("<I", d, o)[0]
        p_off = struct.unpack_from("<I", d, o + 4)[0]
        p_vaddr = struct.unpack_from("<I", d, o + 8)[0]
        p_filesz = struct.unpack_from("<I", d, o + 16)[0]
        if p_type == 3:                       # PT_INTERP
            interp = d[p_off:d.index(b"\x00", p_off)].decode()
        elif p_type == 2:                     # PT_DYNAMIC
            dyn = (p_off, p_filesz)
        elif p_type == 1:                     # PT_LOAD
            loads.append((p_vaddr, p_off, p_filesz))
    if not dyn:
        return interp, []

    def v2o(v):
        for va, off, sz in loads:
            if va <= v < va + sz:
                return off + (v - va)
        return None

    off, sz = dyn
    ents, strtab_v = [], None
    for j in range(0, sz, 8):
        tag, val = struct.unpack_from("<II", d, off + j)
        if tag == 0:
            break
        ents.append((tag, val))
        if tag == 5:                          # DT_STRTAB
            strtab_v = val
    needed = []
    if strtab_v is not None:
        so = v2o(strtab_v)
        for tag, val in ents:
            if tag == 1:                      # DT_NEEDED
                o = so + val
                needed.append(d[o:d.index(b"\x00", o)].decode())
    return interp, needed


def find(soname):
    for d in BUSQ:
        p = f"{d}/{soname}"
        if os.path.exists(p):
            return os.path.realpath(p)
    return None


def closure(roots):
    seen, missing, order = set(), [], []
    stack = list(roots)
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        interp, needed = elf_info(p)
        order.append((p, interp, needed))
        for n in needed:
            if n in [os.path.basename(x) for x in seen]:
                continue
            q = find(n)
            if q:
                stack.append(q)
            else:
                missing.append(n)
    return order, sorted(set(missing))


roots = [f"{WR}/sbin/wpa_supplicant", f"{WR}/sbin/wpa_cli"]
roots = [r for r in roots if os.path.isfile(r)]
order, missing = closure(roots)
print(f"ficheros ELF en el cierre: {len(order)}")
for p, interp, needed in order:
    print(f"  {os.path.basename(p):<28} interp={interp}  needed={len(needed)}")
print(f"\nSONAMES QUE FALTAN ({len(missing)}):")
for m in missing:
    print("  ", m)
