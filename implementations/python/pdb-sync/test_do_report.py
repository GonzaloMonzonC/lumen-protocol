#!/usr/bin/env python3
"""Test: carga el script REPORT.m en ^ROUTINE y lo ejecuta con M-Light v2."""

import sys, os

# Añadir paths
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync"))

from pdb_tools import tool_set, tool_get, tool_order

# ── 1. Cargar REPORT.m en ^ROUTINE ──
print("📦 Cargando REPORT.m en ^ROUTINE...")

with open(os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync/routines/REPORT.m")) as f:
    content = f.read()

# Almacenar línea por línea (como MSM: ^ROUTINE("name",line_no) = code)
lines = content.split('\n')
for i, line in enumerate(lines, 1):
    if line.strip():
        tool_set({"ns": "ROUTINE", "subs": ["REPORT", str(i)], "value": line})

print(f"  ✅ {len(lines)} líneas almacenadas en ^ROUTINE(\"REPORT\")")

# ── 2. Ejecutar con M-Light v2 ──
print("\n⚡ Ejecutando DO ^REPORT con M-Light v2...\n")

from m_routines import RoutineExecutor

executor = RoutineExecutor()
result = executor.exec("REPORT")

if "error" in result:
    print(f"❌ Error: {result['error']}")
else:
    print(f"✅ Ejecución completada")
    print(f"   Result: {result.get('result')}")
    print(f"   Vars: {list(result.get('vars', {}).keys())[:10]}")

# ── 3. Verificar contenido ──
print("\n📋 Verificando ^ROUTINE(\"REPORT\"):")
r = tool_get({"ns": "ROUTINE", "subs": ["REPORT"]})
print(f"   Existe: {r.get('success')}")

# Listar primeras líneas
r2 = tool_order({"ns": "ROUTINE", "subs": ["REPORT", ""], "direction": 1})
print(f"   Primera línea key: {r2.get('value')}")

r3 = tool_get({"ns": "ROUTINE", "subs": ["REPORT", "1"]})
print(f"   Línea 1: {str(r3.get('value', ''))[:80]}")
