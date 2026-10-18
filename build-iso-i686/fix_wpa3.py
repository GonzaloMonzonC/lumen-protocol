#!/usr/bin/env python3
"""Integra el resolvedor de DT_NEEDED en copy_wpa (en vez de lista fija de sonames)."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

# 1) sustituir la lista fija por los helpers del resolvedor
old_list = '# sonames que pide wpa_supplicant (leidos del ELF) + NSS\nWPA_SO = ["libc.so.6", "libm.so.6", "libcrypto.so.3", "libssl.so.3",\n          "libdbus-1.so.3", "libnl-3.so.200", "libnl-genl-3.so.200",\n          "libnl-route-3.so.200", "libpcsclite.so.1",\n          "libnss_dns.so.2", "libnss_files.so.2", "libresolv.so.2"]'
new_list = '''import struct

WPA_BUSQ = [WPA_LIB, f"{WPA_ROOT}/usr/lib/i386-linux-gnu",
            f"{WPA_ROOT}/lib", f"{WPA_ROOT}/usr/lib"]


def _elf_needed(path):
    """(interp, [DT_NEEDED]) de un ELF de 32 bits. Sin ldd."""
    d = open(path, "rb").read()
    if d[:4] != b"\\x7fELF" or d[4] != 1:
        return None, []
    phoff = struct.unpack_from("<I", d, 28)[0]
    phes = struct.unpack_from("<H", d, 42)[0]
    phnum = struct.unpack_from("<H", d, 44)[0]
    dyn, loads = None, []
    for i in range(phnum):
        o = phoff + i * phes
        t = struct.unpack_from("<I", d, o)[0]
        po = struct.unpack_from("<I", d, o + 4)[0]
        pv = struct.unpack_from("<I", d, o + 8)[0]
        pz = struct.unpack_from("<I", d, o + 16)[0]
        if t == 2:
            dyn = (po, pz)
        elif t == 1:
            loads.append((pv, po, pz))
    if not dyn:
        return None, []

    def v2o(v):
        for va, off, sz in loads:
            if va <= v < va + sz:
                return off + (v - va)
    o, z = dyn
    ents, strv = [], None
    for j in range(0, z, 8):
        tag, val = struct.unpack_from("<II", d, o + j)
        if tag == 0:
            break
        ents.append((tag, val))
        if tag == 5:
            strv = val
    need = []
    if strv is not None:
        so = v2o(strv)
        for tag, val in ents:
            if tag == 1:
                p = so + val
                need.append(d[p:d.index(b"\\x00", p)].decode())
    return None, need


def _find_so(name):
    for d in WPA_BUSQ:
        if os.path.exists(f"{d}/{name}"):
            return os.path.realpath(f"{d}/{name}")
    return None


def _wpa_closure(roots):
    """cierre transitivo de librerias (rutas reales)."""
    seen, out = set(), []
    stack = [r for r in roots if os.path.isfile(r)]
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        _, need = _elf_needed(p)
        for n in need:
            q = _find_so(n)
            if q and q not in seen:
                stack.append(q)
                out.append(q)
    return out'''
assert old_list in s, "no encontre WPA_SO"
s = s.replace(old_list, new_list, 1)

# 2) sustituir el bucle de copia por el cierre
old_loop = '''    n = 0
    busq = [WPA_LIB, f"{WPA_ROOT}/usr/lib/i386-linux-gnu"]
    for so in WPA_SO:
        p = None
        for d in busq:
            if os.path.exists(f"{d}/{so}"):
                p = f"{d}/{so}"
                break
        if p:
            shutil.copy2(os.path.realpath(p), f"{OUT}/lib/i386-linux-gnu/{so}")
            n += 1
        else:
            print(f"  !! sin {so}")'''
new_loop = '''    cli = f"{WPA_ROOT}/sbin/wpa_cli"
    libs = _wpa_closure([src, cli])
    n = 0
    for p in libs:
        if "/lib/" in p.replace("\\\\", "/") and os.path.basename(p).startswith("ld-"):
            continue
        name = os.path.basename(p)
        shutil.copy2(p, f"{OUT}/lib/i386-linux-gnu/{name}")
        n += 1'''
assert old_loop in s, "no encontre el bucle de copia"
s = s.replace(old_loop, new_loop, 1)

# quitar la copia duplicada de wpa_cli (ya se hace antes)
s = s.replace('''    # wpa_cli comparte las mismas libs
    cli = f"{WPA_ROOT}/sbin/wpa_cli"
    if os.path.isfile(cli):
        shutil.copy2(cli, f"{OUT}/bin/wpa_cli")''',
'''    # wpa_cli comparte las mismas libs
    if os.path.isfile(cli):
        shutil.copy2(cli, f"{OUT}/bin/wpa_cli")''', 1)

open(P, "w", encoding="utf-8", newline="").write(s)
import py_compile
py_compile.compile(P, doraise=True)
print("PATCH OK y compila")
