#!/usr/bin/env python3
"""Fix: copiar cada libreria con su SONAME, no con su nombre real.
El loader busca 'libdbus-1.so.3'; si solo existe 'libdbus-1.so.3.32.4' no la encuentra."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

old_fn = '''def _wpa_closure(roots):
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
new_fn = '''def _wpa_closure(roots):
    """cierre transitivo: devuelve {SONAME: ruta_real} (el loader busca el SONAME)."""
    seen, out = set(), {}
    stack = [r for r in roots if os.path.isfile(r)]
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        _, need = _elf_needed(p)
        for n in need:
            q = _find_so(n)
            if q:
                out[n] = q
                if q not in seen:
                    stack.append(q)
    return out'''
assert old_fn in s, "no encontre _wpa_closure"
s = s.replace(old_fn, new_fn, 1)

old_loop = '''    cli = f"{WPA_ROOT}/sbin/wpa_cli"
    libs = _wpa_closure([src, cli])
    n = 0
    for p in libs:
        if "/lib/" in p.replace("\\\\", "/") and os.path.basename(p).startswith("ld-"):
            continue
        name = os.path.basename(p)
        shutil.copy2(p, f"{OUT}/lib/i386-linux-gnu/{name}")
        n += 1'''
new_loop = '''    cli = f"{WPA_ROOT}/sbin/wpa_cli"
    libs = _wpa_closure([src, cli])
    n = 0
    for soname, p in libs.items():
        if os.path.basename(p).startswith("ld-"):
            continue          # el loader va aparte, en /lib/ld-linux.so.2
        shutil.copy2(p, f"{OUT}/lib/i386-linux-gnu/{soname}")
        n += 1'''
assert old_loop in s, "no encontre el bucle"
s = s.replace(old_loop, new_loop, 1)

open(P, "w", encoding="utf-8", newline="").write(s)
import py_compile
py_compile.compile(P, doraise=True)
print("PATCH OK y compila")
