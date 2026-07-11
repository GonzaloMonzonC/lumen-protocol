#!/usr/bin/env python3
"""Test M-Light v2 con scripts M reales — progresivo."""

import sys, os
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync"))

from pdb_tools import tool_set
from m_routines import RoutineExecutor, register

# ── Test 1: Script básico ──
print("🧪 TEST 1: Script básico SET/WRITE/FOR\n")

register("TEST1", """
S x=42
W x
F i=1:1:3 S t=i
""")

executor = RoutineExecutor()
r = executor.exec("TEST1")
print(f"  Result: {r.get('result')}")
print(f"  Vars: {r.get('vars', {})}")
print(f"  Error: {r.get('error', 'none')}")
print()

# ── Test 2: Script con args ──
print("🧪 TEST 2: Script con argumentos\n")

register("ECHO2", """
S result=$1
W result
""")

r2 = executor.exec("ECHO2", ["hello from M-Light!"])
print(f"  Vars: {r2.get('vars', {})}")
print(f"  Error: {r2.get('error', 'none')}")
print()

# ── Test 3: Script multi-línea complejo ──
print("🧪 TEST 3: Script multi-namespace\n")

register("SCANLITE", """
S total=0
S ns=System
S total=total+1
""")

r3 = executor.exec("SCANLITE")
print(f"  Vars: {r3.get('vars', {})}")
print(f"  Error: {r3.get('error', 'none')}")
print()

# ── Test 4: Cargar desde ^ROUTINE y ejecutar ──
print("🧪 TEST 4: DO desde ^ROUTINE\n")

from pdb_tools import tool_set, tool_get
tool_set({"ns": "ROUTINE", "subs": ["R4", "1"], "value": "S msg=42"})
tool_set({"ns": "ROUTINE", "subs": ["R4", "2"], "value": "W msg"})

r4 = executor.exec("R4")
print(f"  Cargado desde ^ROUTINE: {r4.get('vars', {})}")

# ── Benchmark contra eval() ──
print("\n📊 BENCHMARK: StackVM vs Python eval()\n")
import time

# Misma operación: SET x=0, FOR i=1:1:1000, x=x+i
code = "S x=0 F i=1:1:1000 S x=x+i"

# StackVM
vm_start = time.time()
for _ in range(100):
    executor2 = RoutineExecutor()
    register("BENCH", code)
    executor2.exec("BENCH")
vm_time = time.time() - vm_start

# Python eval() (simulado)
py_start = time.time()
for _ in range(100):
    x = 0
    for i in range(1, 1001):
        x = x + i
py_time = time.time() - py_start

print(f"  StackVM: {vm_time:.3f}s (100 ejecuciones)")
print(f"  Python:  {py_time:.3f}s (100 ejecuciones)")
print(f"  Ratio:   {vm_time/py_time:.1f}x (Zalo: objetivo < 2x)")
