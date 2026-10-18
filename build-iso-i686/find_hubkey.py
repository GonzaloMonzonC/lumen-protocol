#!/usr/bin/env python3
"""Localiza ^CONFIG("ddp_hmac_key") en las .db y dice donde aparece.
NO imprime la clave: solo huella (primeros 6 + ultimos 4)."""
import glob, os, re, subprocess, hashlib

RAIZ = "C:/Users/gonzalo/Documents/GitHub/mvm-nas"
patron = re.compile(rb'ddp_hmac_key', re.I)
# tras la clave viene el valor en hex de 64 chars
valre = re.compile(rb'ddp_hmac_key[^\x00]{0,4}([0-9a-fA-F]{64})')

hallazgos = {}
for db in glob.glob(f"{RAIZ}/*.db") + glob.glob(f"{RAIZ}/**/*.db", recursive=True):
    try:
        d = open(db, "rb").read()
    except Exception:
        continue
    for m in valre.finditer(d):
        k = m.group(1).decode()
        hallazgos.setdefault(k, []).append(os.path.relpath(db, RAIZ))

print(f"claves distintas encontradas: {len(hallazgos)}")
for k, ficheros in hallazgos.items():
    print(f"  clave {k[:6]}...{k[-4:]} (len={len(k)}, sha256[:8]={hashlib.sha256(k.encode()).hexdigest()[:8]})")
    for f in sorted(set(ficheros)):
        print(f"      en {f}")

# ¿alguno de esos ficheros esta VERSIONADO?
print("\n¿versionados en git?")
for k, ficheros in hallazgos.items():
    for f in sorted(set(ficheros)):
        r = subprocess.run(["git", "ls-files", "--error-unmatch", f],
                           cwd=RAIZ, capture_output=True)
        print(f"  {'SI  <-- OJO' if r.returncode == 0 else 'no'}  {f}")
