#!/usr/bin/env python3
"""Test REPORT.m completo con M-Light v2."""

import sys, os
import _paths  # noqa: F401  # sys.path del stack PDB

from pdb_tools import tool_set, tool_kill
from m_routines import RoutineExecutor, register

# ── 1. Cargar REPORT.m en ^ROUTINE ──
print("📦 Cargando REPORT.m en ^ROUTINE...")

with open(_paths.REPORT_M) as f:
    content = f.read()

# Limpiar versión anterior
tool_kill({"ns": "ROUTINE", "subs": ["REPORT"]})

# Almacenar línea por línea
lines = content.split('\n')
for i, line in enumerate(lines, 1):
    if line.strip():
        tool_set({"ns": "ROUTINE", "subs": ["REPORT", str(i)], "value": line})

print(f"  ✅ {len(lines)} líneas en ^ROUTINE(\"REPORT\")")
print(f"  1: {lines[0][:60]}" if lines else "  (empty)")

# ── 2. Ejecutar con M-Light v2 ──
print("\n⚡ Ejecutando DO ^REPORT...\n")

executor = RoutineExecutor()
result = executor.exec("REPORT")

if "error" in result:
    print(f"❌ Error: {result['error']}")
else:
    print(f"✅ Completado")
    print(f"   Result: {result.get('result')}")
    print(f"   Vars: {list(result.get('vars', {}).keys())[:10]}")

# ── 3. Verificar que el script se cargó correctamente ──
print("\n📋 Verificación:")
from pdb_tools import tool_order, tool_get
r = tool_order({"ns": "ROUTINE", "subs": ["REPORT", ""], "direction": 1})
print(f"   Primera línea: {r}")
r2 = tool_get({"ns": "ROUTINE", "subs": ["REPORT", "11"]})
print(f"   Línea 11: {str(r2.get('value', ''))[:80]}")
