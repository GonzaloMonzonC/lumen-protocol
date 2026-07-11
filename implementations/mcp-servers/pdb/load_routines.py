#!/usr/bin/env python3
"""
load_routines.py — Carga un fichero ^%RS en ^ROUTINE(name, line) = code

Uso: python load_routines.py rutinas.txt

Formato ^%RS:
  Cabecera: timestamp
  Línea en blanco
  Para cada rutina:
    Nombre (primera línea)
    Líneas de código (nombre + espacios + código)
  Separador entre rutinas: línea en blanco + siguiente nombre

Carga en PDB:
  ^ROUTINE(nombre, numero_linea) = código
  ^ROUTINE("INDEX", nombre) = ""  (índice de rutinas)

Author: Hermes + CadencesLab
Date: 2026-07-11
"""

import sys, os, re

sys.path.insert(0, os.path.expanduser(
    "~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"
))
from pdb_tools import tool_set

def load_routines(filepath):
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    routines = {}
    current_routine = None
    line_num = 0
    in_header = True

    for line in lines:
        stripped = line.rstrip('\n\r')

        # Skip header (timestamp line + blank line)
        if in_header:
            if not stripped or 'PM' in stripped or 'AM' in stripped:
                continue
            in_header = False

        # Blank line = separator
        if not stripped:
            if current_routine:
                routines[current_routine] = routines.get(current_routine, [])
            current_routine = None
            continue

        # New routine name (single word, no leading spaces/tabs)
        if not stripped[0] in (' ', '\t', ';') and current_routine is None:
            current_routine = stripped.split()[0] if stripped.split() else stripped
            routines[current_routine] = routines.get(current_routine, [])
            continue

        # Code line
        if current_routine:
            # Clean: remove leading spaces but keep structure
            code = stripped.strip()
            routines[current_routine].append(code)

    # Last routine
    if current_routine:
        routines[current_routine] = routines.get(current_routine, [])

    return routines

def store_in_pdb(routines):
    """Guardar en ^ROUTINE y ^ROUTINE("INDEX")."""
    count = 0
    for name, lines in routines.items():
        if not name:
            continue
        for i, code in enumerate(lines):
            # ^ROUTINE(name, line_num) = code
            result = tool_set({
                "ns": "ROUTINE",
                "subs": [name, i + 1],
                "value": code
            })
            if result.get("success"):
                count += 1

        # ^ROUTINE("INDEX", name) = "" (índice)
        tool_set({
            "ns": "ROUTINE",
            "subs": ["INDEX", name],
            "value": ""
        })

    return count

if __name__ == "__main__":
    filepath = sys.argv[1] if len(sys.argv) > 1 else "rutinas.txt"
    print(f"📂 Cargando {filepath}...")

    routines = load_routines(filepath)
    print(f"📋 {len(routines)} rutinas encontradas")

    count = store_in_pdb(routines)
    print(f"💾 {count} líneas guardadas en ^ROUTINE")

    # Mostrar resumen
    print(f"\n🔍 ^ROUTINE(\"INDEX\"):")
    from pdb_tools import tool_order
    key = ""
    while True:
        r = tool_order({"ns": "ROUTINE", "subs": ["INDEX", key], "direction": 1})
        if not r.get("success") or not r.get("value"):
            break
        key = r["value"]
        # Contar líneas de esta rutina
        line_count = 0
        k2 = ""
        while True:
            r2 = tool_order({"ns": "ROUTINE", "subs": [key, k2], "direction": 1})
            if not r2.get("success") or not r2.get("value"):
                break
            k2 = r2["value"]
            if k2 != "INDEX":
                line_count += 1
        print(f"  {key}: {line_count} líneas")
