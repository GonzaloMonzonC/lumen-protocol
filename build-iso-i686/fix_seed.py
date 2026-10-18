#!/usr/bin/env python3
"""Anade el SEED LOCAL al build i686 (lo que hace _build_initramfs.sh en x86_64).

lumenos/seed-local.conf (GITIGNORED, lleva token) se copia como M a
/opt/mvm/seed-local.m. Sin esto el nodo usa el proveedor directo -> 401.
"""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

anchor = "def copy_firmware():"
new = '''MVM_REPO = "C:/Users/gonzalo/Documents/GitHub/mvm-nas"


def copy_seed():
    """SEED LOCAL: apunta la cadena LLM al nodo-puerta (neferu :8140).
    Sin esto el nodo intenta el proveedor directo y da 401 Authentication Fails.
    El fichero lleva un TOKEN: esta GITIGNORED, NO versionar nunca."""
    conf = f"{MVM_REPO}/lumenos/seed-local.conf"
    if os.path.isfile(conf):
        lineas = [l for l in open(conf, encoding="utf-8").read().splitlines()
                  if l.strip() and not l.lstrip().startswith("#")]
        os.makedirs(f"{OUT}/opt/mvm", exist_ok=True)
        with open(f"{OUT}/opt/mvm/seed-local.m", "w", newline="\\n") as f:
            f.write("\\n".join(lineas) + "\\n")
        print(f"  seed-local.m incluido ({len(lineas)} lineas de M) -> puerta LLM")
    else:
        print("  sin seed-local.conf: el nodo usara el proveedor directo (401 probable)")
    clave = f"{MVM_REPO}/lumenos/serve.key"
    if os.path.isfile(clave):
        with open(f"{OUT}/opt/mvm/serve.key", "w", newline="\\n") as f:
            f.write(open(clave, encoding="utf-8").read().strip() + "\\n")
        print("  serve.key incluido (la puerta :8140 se abrira con auth)")


'''
assert anchor in s, "no encontre copy_firmware"
s = s.replace(anchor, new + anchor, 1)

old = "    copy_firmware()\n    copy_wpa()"
new2 = "    copy_firmware()\n    copy_wpa()\n    copy_seed()"
assert old in s, "no encontre las llamadas"
s = s.replace(old, new2, 1)

open(P, "w", encoding="utf-8", newline="").write(s)
import py_compile
py_compile.compile(P, doraise=True)
print("PATCH OK y compila")
