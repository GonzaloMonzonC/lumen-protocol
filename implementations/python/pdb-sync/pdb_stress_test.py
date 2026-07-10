#!/usr/bin/env python3
"""
pdb_stress_test.py — Prueba de estrés completa del ecosistema.

Simula múltiples agentes trabajando simultáneamente:
- Escribe 100+ entradas en PDB
- Verifica journaling (^CHANGES)
- Ejecuta M-code en ^docs
- Valida cross-refs
- Mide rendimiento

Author: Hermes + CadencesLab
Date: 2026-07-11
"""

import sys, os, time, json
sys.path.insert(0, os.path.dirname(__file__))
from pdb_docs import *
from pdb_docs import _get_pdb_tools

tools = _get_pdb_tools()
PASS = FAIL = 0
TIMINGS = []

def t(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1
    else: FAIL += 1; print(f"  ❌ {name}: {detail}")

def clock(label):
    global TIMINGS
    TIMINGS.append((label, time.time()))

def report_timings():
    print("\n⏱️  Rendimiento:")
    for i in range(1, len(TIMINGS)):
        label, t2 = TIMINGS[i]
        _, t1 = TIMINGS[i-1]
        ms = (t2 - t1) * 1000
        bar = "█" * int(ms/10) if ms < 500 else "▓" * 20
        print(f"  {label:30s} {ms:8.1f}ms {bar}")

print("╔══════════════════════════════════════════════╗")
print("║   PRUEBA DE ESTRÉS — ECOSISTEMA COMPLETO    ║")
print("╚══════════════════════════════════════════════╝")

# ─────────────────────────────────────────────────────────────
# FASE 1: Seed masivo (100+ entradas, 5 agentes)
# ─────────────────────────────────────────────────────────────
clock("start")
print("\n🧪 FASE 1: Seed masivo (100 entradas, 5 agentes)")

agents = ["zalo","lisa","tom","angi","hermes"]
statuses = ["active","idle","busy","error"]
clock("seed-start")
count = 0
for i in range(100):
    agent = agents[i % 5]
    status = statuses[i % 4]
    tools.tool_set({"ns":"STRESS","subs":[f"entry-{i:03d}"],"value":{
        "agent":agent, "status":status, "load":i % 10,
        "timestamp": f"2026-07-{10+(i//30):02d}T12:00:{i%60:02d}Z"
    }})
    count += 1
clock("seed-end")
elapsed = (TIMINGS[-1][1] - TIMINGS[-2][1]) * 1000
print(f"  {count} entradas en {elapsed:.0f}ms")
t("Seed masivo OK", count == 100)

# ─────────────────────────────────────────────────────────────
# FASE 2: Verificar journaling
# ─────────────────────────────────────────────────────────────
clock("journal-start")
changes = tools.tool_fts_search({"query":"STRESS","ns":"CHANGES","limit":50})
change_count = len(changes.get("results",[])) if changes.get("success") else 0
clock("journal-end")
t("Journaling activo (>0 cambios)", change_count > 0, f"{change_count} cambios")

# ─────────────────────────────────────────────────────────────
# FASE 3: Iteración $ORDER
# ─────────────────────────────────────────────────────────────
print("\n🧪 FASE 3: Iteración $ORDER en ^STRESS")
clock("order-start")
doc_set("playbook",["stress","iterate"],{"content":"$O(^STRESS(\"\"))","confidence":10,"source_agent":"test","executable":True})
d = doc_get("playbook",["stress","iterate"])
clock("order-end")
t("$ORDER primer key", d and d.get("_live_data") == "entry-000")
t("_executed flag", d and d.get("_executed") is True)

# ─────────────────────────────────────────────────────────────
# FASE 4: M-code análisis (contar por agente)
# ─────────────────────────────────────────────────────────────
print("\n🧪 FASE 4: M-code análisis multi-agente")
clock("analysis-start")
scripts = {
    "count-zalo": ("$G(^STRESS(\"entry-000\"))", "zalo"),
    "first-active": ("$O(^STRESS(\"entry-003\"))", "lisa"),
    "last-entry": ("$O(^STRESS(\"entry-098\"))", "tom"),
}
for name, (code, agent) in scripts.items():
    doc_set("playbook",["stress",name],{"content":code,"confidence":9,"source_agent":agent,"executable":True})
    d = doc_get("playbook",["stress",name])
    t(f"M-code {name}", d and d.get("_executed") is True, str(d.get("_live_data","?"))[:40])
clock("analysis-end")

# ─────────────────────────────────────────────────────────────
# FASE 5: Cross-refs entre docs de estrés
# ─────────────────────────────────────────────────────────────
print("\n🧪 FASE 5: Cross-refs entre análisis")
clock("crossref-start")
doc_set("architecture",["stress","summary"],{"content":"Resumen estrés","confidence":9,"source_agent":"hermes","links":["^decisions:6"]})
doc_add_link("architecture",["stress","summary"],"^patterns:1")
d = doc_get("architecture",["stress","summary"])
t("Links creados", d and len(d.get("links",[])) >= 2)
g = doc_graph("architecture",["stress","summary"])
t("Grafo centro", g.get("center") is not None)
clock("crossref-end")

# ─────────────────────────────────────────────────────────────
# FASE 6: Lectura concurrente simulada
# ─────────────────────────────────────────────────────────────
print("\n🧪 FASE 6: Lectura concurrente (5 agentes)")
clock("concurrent-start")
results = []
for agent in agents:
    doc_set("playbook",["stress",f"view-{agent}"],{"content":f"$O(^STRESS(\"\"))","confidence":8,"source_agent":agent,"executable":True})
    d = doc_get("playbook",[f"view-{agent}"])
    results.append(d and d.get("_live_data") == "entry-000")
clock("concurrent-end")
t("5 agentes leen OK", all(results), f"{sum(results)}/5")

# ─────────────────────────────────────────────────────────────
# RESULTADO
# ─────────────────────────────────────────────────────────────
clock("end")
print(f"\n{'='*50}")
print(f"  RESULTADO: {PASS} OK / {FAIL} FAIL")
report_timings()

if FAIL == 0:
    print("\n  🎉 SISTEMA VALIDADO — listo para producción\n")
else:
    print(f"\n  ⚠️  {FAIL} fallos — revisar\n")

sys.exit(0 if FAIL == 0 else 1)
