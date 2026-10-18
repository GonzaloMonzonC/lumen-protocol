#!/usr/bin/env python3
"""FIX de rutinas en LOS DOS builds:
  - i686: solo copiaba deploy/routines (23) -> faltaban las 64 del repo. Ahora copia
          routines/*.m + deploy/routines/*.m, con DEPLOY MANDANDO.
  - x86_64: hacia al reves (el repo ganaba) -> %HB.m salia SIN el paso 3 (y con dos
          lineas rotas). Ahora deploy sobrescribe.
Razon: deploy/routines es donde vive lo especifico de la ISO (rutinas parcheadas).
"""
from pathlib import Path

# ───── i686 ─────
pi = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py")
s = open(pi, encoding="utf-8", newline="").read()
old_i = '''    for f in os.listdir(f"{MVN}/deploy/routines"):'''
new_i = '''    # 02-oct-2026: el build x86_64 copiaba routines/ + deploy/ (87) y este solo
    # deploy/ (23) -> la ISO i686 salia SIN 64 rutinas. Ahora igual: primero las
    # del repo, luego deploy/routines que MANDA (trae los parches de la ISO).
    _r = f"{MVN}/routines"
    if os.path.isdir(_r):
        for f in os.listdir(_r):
            if f.endswith(".m"):
                shutil.copy2(os.path.join(_r, f), f"{OUT}/opt/mvm/routines/{f}")
    for f in os.listdir(f"{MVN}/deploy/routines"):'''
assert old_i in s, "no encontre el bucle del i686"
s = s.replace(old_i, new_i, 1)
open(pi, "w", encoding="utf-8", newline="").write(s)
print("i686 OK: routines/ + deploy/ (deploy manda)")

# ───── x86_64 ─────
ps = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/_build_initramfs.sh")
t = open(ps, encoding="utf-8", newline="").read()
old_s = '''cp "$MVM"/routines/*.m "$ROOT/opt/mvm/routines/" 2>/dev/null || true
ADDED=0
for f in "$MVM"/deploy/routines/*.m; do
  b=$(basename "$f")
  if [ -f "$ROOT/opt/mvm/routines/$b" ]; then
    :
  else
    cp "$f" "$ROOT/opt/mvm/routines/"; ADDED=$((ADDED+1))
  fi
done
echo "    rutinas: $(ls "$ROOT/opt/mvm/routines" | wc -l) (+$ADDED desde deploy)"'''
new_s = '''cp "$MVM"/routines/*.m "$ROOT/opt/mvm/routines/" 2>/dev/null || true
ADDED=0
# 02-oct-2026: DEPLOY MANDA. Antes ganaba el repo y %HB.m se quedaba con la
# version SIN el paso 3 (guardar la memoria en el latido) y con dos lineas
# rotas (' TS' / ' TC' sueltas) -> la ISO salia coja sin que se notara.
for f in "$MVM"/deploy/routines/*.m; do
  b=$(basename "$f")
  cp "$f" "$ROOT/opt/mvm/routines/"
  ADDED=$((ADDED+1))
done
echo "    rutinas: $(ls "$ROOT/opt/mvm/routines" | wc -l) ($ADDED sobrescritas/anadidas desde deploy)"'''
assert old_s in t, "no encontre el bloque del x86_64"
t = t.replace(old_s, new_s, 1)
open(ps, "w", encoding="utf-8", newline="").write(t)
print("x86_64 OK: deploy sobrescribe")
