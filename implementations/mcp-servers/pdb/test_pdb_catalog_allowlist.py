#!/usr/bin/env python3
"""test_pdb_catalog_allowlist.py — H6

El PDB exponia 19 de 66 handlers. Hay un doc previo que apunta a curaduria
deliberada por coste de tokens, asi que el defecto no era esconder 47: era
esconder la ESCRITURA de un pipeline cuya lectura estaba expuesta, y no decirlo.

Este test fija el contrato de los dos perfiles contra
tests/allowlist_pdb_tools.txt. Falla si el catalogo cambia sin actualizar el
allowlist Y el doc -> la curaduria deja de ser un accidente.

Sin dependencias externas, PDB temporal.
    python test_pdb_catalog_allowlist.py [-v]
"""
import os
import sys
import tempfile
from pathlib import Path


def find_pdb():
    for parent in Path(__file__).resolve().parents:
        cand = parent / "implementations/mcp-servers/pdb"
        if (cand / "pdb_tools.py").is_file():
            return cand
    return Path.home() / "Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"


def load(pdbdir):
    sys.path.insert(0, str(pdbdir))
    os.environ.setdefault("PDB_PATH", tempfile.mktemp(suffix=".db"))
    import pdb_tools
    return pdb_tools


def read_allowlist(path):
    agente, admin = set(), set()
    if not path.is_file():
        return None, None
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) != 2:
            continue
        perfil, nombre = parts
        if perfil == "agente":
            agente.add(nombre)
        else:
            admin.add(nombre)
    # admin es el SUPERCONJUNTO: agente + las exclusivas de admin
    return agente, admin | agente


def main():
    verbose = "-v" in sys.argv
    pdbdir = find_pdb()
    if not (pdbdir / "pdb_tools.py").is_file():
        print(f"SKIP: no encuentro {pdbdir}/pdb_tools.py")
        return 0

    t = load(pdbdir)
    allow_path = pdbdir / "tests" / "allowlist_pdb_tools.txt"
    ag_wl, ad_wl = read_allowlist(allow_path)

    fails = []
    if ag_wl is None:
        print(f"FALLO: falta el allowlist {allow_path}")
        return 1

    # ── 1. los perfiles existen y devuelven lo que deben ──
    try:
        cat_ag = {x["name"] for x in t.tools_for_profile(t.PROFILE_AGENT)}
        cat_ad = {x["name"] for x in t.tools_for_profile(t.PROFILE_ADMIN)}
    except AttributeError as e:
        print(f"FALLO: faltan las piezas de H6 ({e})")
        return 1

    print(f"agente (codigo) : {len(cat_ag)}")
    print(f"agente (allowlist): {len(ag_wl)}")
    print(f"admin  (codigo) : {len(cat_ad)}")
    print(f"admin  (allowlist): {len(ad_wl)}")

    if cat_ag != ag_wl:
        extra, falta = sorted(cat_ag - ag_wl), sorted(ag_wl - cat_ag)
        if extra:
            fails.append(f"tools NUEVAS en el perfil agente sin declarar en el allowlist: {extra}")
        if falta:
            fails.append(f"tools en el allowlist ausentes del perfil agente: {falta}")

    if cat_ad != ad_wl:
        extra, falta = sorted(cat_ad - ad_wl), sorted(ad_wl - cat_ad)
        if extra:
            fails.append(f"tools NUEVAS en el perfil admin sin declarar en el allowlist: {extra}")
        if falta:
            fails.append(f"tools en el allowlist ausentes del perfil admin: {falta}")

    # ── 2. el admin cubre TODOS los handlers (si no, hay tools inalcanzables) ──
    handlers = set(t.HANDLERS)
    if cat_ad != handlers:
        faltan = sorted(handlers - cat_ad)
        sobran = sorted(cat_ad - handlers)
        if faltan:
            fails.append(f"handlers inalcanzables incluso en admin: {faltan}")
        if sobran:
            fails.append(f"el perfil admin expone nombres sin handler: {sobran}")
    else:
        print(f"admin cubre los {len(handlers)} handlers: OK")

    # ── 3. el agente es SUBCONJUNTO del admin (nada invisible para el operador) ──
    huerfanas = sorted(cat_ag - cat_ad)
    if huerfanas:
        fails.append(f"tools del agente que el admin NO tiene: {huerfanas}")
    else:
        print(f"agente esta contenido en admin: OK")

    # ── 4. el agente no crece sin querer: es el catalogo corto ──
    if len(cat_ag) > 24:
        fails.append(f"el perfil agente tiene {len(cat_ag)} tools: se supone que es el corto "
                     f"(<=24). Si es deliberado, actualiza el allowlist Y docs/mcp-catalog.md")

    # ── 5. toda tool expuesta tiene inputSchema (un cliente estricto lo exige) ──
    for perfil, cat in (("agente", t.tools_for_profile(t.PROFILE_AGENT)),
                        ("admin", t.tools_for_profile(t.PROFILE_ADMIN))):
        sin = [x["name"] for x in cat if not isinstance(x.get("inputSchema"), dict)]
        if sin:
            fails.append(f"perfil {perfil}: tools sin inputSchema: {sin}")

    # ── 6. resolve_profile: un typo NUNCA abre las 66 ──
    if t.resolve_profile(["--profile", "basura"]) != t.PROFILE_AGENT:
        fails.append("un --profile invalido no cae a 'agente': abriria las 66 por un typo")
    if t.resolve_profile([]) != t.PROFILE_AGENT:
        fails.append("sin argumentos el perfil por defecto no es 'agente'")
    if t.resolve_profile(["--profile", "admin"]) != t.PROFILE_ADMIN:
        fails.append("--profile admin no activa el perfil admin")
    else:
        print("resolve_profile: OK (admin opt-in, typo -> agente)")

    if verbose:
        print(f"\nsolo en admin ({len(cat_ad - cat_ag)}):")
        print(", ".join(sorted(cat_ad - cat_ag)))

    print()
    if fails:
        print(f"FALLO ({len(fails)})")
        for f in fails:
            print(f"   - {f}")
        return 1
    print("PASS: catalogo de los dos perfiles fijado por allowlist")
    return 0


if __name__ == "__main__":
    sys.exit(main())
