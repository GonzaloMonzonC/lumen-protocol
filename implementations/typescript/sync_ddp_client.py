#!/usr/bin/env python3
"""Sync del cliente DDP-LUMEN TS canónico a los workers del ecosistema.

Fuente única: lumen-protocol/implementations/typescript/src/ddp-client.ts
Los workers VENDEN este fichero (regla SSOT de código, Gonzalo 14-08-2026).

Uso:
    python sync_ddp_client.py [--check] [--worker angi|zalo|lisa|tom|gon|campo]

--check   solo verifica divergencias (exit 1 si hay), no copia.
"""
import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # lumen-protocol/ (implementations/typescript/ → 3 up)
CANONICAL = ROOT / "implementations" / "typescript" / "src" / "ddp-client.ts"

WORKERS = {
    "angi": Path.home() / "Documents" / "GitHub" / "Angi" / "src" / "pdb.ts",
    "zalo": Path.home() / "Documents" / "GitHub" / "Zalo" / "src" / "ddp-client.ts",
    "lisa": Path.home() / "Documents" / "GitHub" / "Lisa" / "src" / "ddp-client.ts",
    "tom": Path.home() / "Documents" / "GitHub" / "Tom" / "src" / "ddp-client.ts",
    "gon": Path.home() / "Documents" / "GitHub" / "Gon" / "src" / "ddp-client.ts",
    "campo": Path.home() / "Documents" / "GitHub" / "Campo" / "src" / "ddp-client.ts",
}

def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "MISSING"

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--worker", choices=list(WORKERS) + ["all"], default="all")
    args = ap.parse_args()

    if not CANONICAL.exists():
        print(f"ERROR: canónico no existe: {CANONICAL}")
        return 1

    targets = list(WORKERS) if args.worker == "all" else [args.worker]
    canonical_sha = sha(CANONICAL)
    bad = 0

    for w in targets:
        dest = WORKERS[w]
        if dest.exists() and sha(dest) == canonical_sha:
            print(f"✔ {w}: sincronizado")
            continue
        if args.check:
            print(f"✘ {w}: DIVERGENTE o ausente ({dest.name})")
            bad += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CANONICAL, dest)
        print(f"→ {w}: copiado {CANONICAL.name} → {dest}")

    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
