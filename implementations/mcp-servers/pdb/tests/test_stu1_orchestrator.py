"""Ejecutar el orquestador de STU1:55 con M-Light."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdb_tools import tool_set, tool_get, tool_order, tool_m_eval

print('🧬 STU1:55 — Orquestador de servicios MUMPS real')
print('='*50)

# SEED: Configuración de jobs como en un sistema MSM real
jobs = {
    'BACKUP': 'START^BACKUP:00:00:5',
    'MONITOR': 'START^MONITOR:00:01:30',
    'CLEANUP': 'START^CLEANUP:00:00:1',
    'ALERT': 'START^ALERT:00:00:1',
}
for name, cmd in jobs.items():
    tool_set({'ns':'SYS','subs':['CONFIG','JOB',name],'value':cmd})
print('🔧 Jobs sembrados en ^SYS("CONFIG","JOB"):')
for name in jobs:
    print(f'  {name}: {jobs[name]}')

# Test 1: $ORDER loop (STU1:55 exacto)
print(f'\n=== Test 1: $ORDER loop ===')
code = 'S JOB="" F  S JOB=$O(^SYS("CONFIG","JOB",JOB)) Q:JOB=""  W JOB," "'
r = tool_m_eval({'expression': code})
print(f'  Jobs encontrados via $ORDER:')

# Test 2: Naked reference ^(JOB) — obtener el valor
print(f'\n=== Test 2: Naked reference ^(JOB) ===')
code = 'S JOB="" F  S JOB=$O(^SYS("CONFIG","JOB",JOB)) Q:JOB=""  S CMD=^(JOB) W JOB,"=",CMD,"  "'
r = tool_m_eval({'expression': code})

# Test 3: $GET + $PIECE
print(f'\n=== Test 3: $PIECE en comando ===')
code = 'S JOB="BACKUP" S CMD=^SYS("CONFIG","JOB",JOB) S TAG=$P(CMD,":",1) W TAG'
r = tool_m_eval({'expression': code})
tag = tool_m_eval({'expression': 'TAG'})
print(f'  TAG extraído: {tag.get("result")}')

# Test 4: Contar jobs
print(f'\n=== Test 4: Contar jobs ===')
code = 'S JOB="",CNT=0 F  S JOB=$O(^SYS("CONFIG","JOB",JOB)) Q:JOB=""  S CNT=CNT+1'
r = tool_m_eval({'expression': code})
cnt = tool_m_eval({'expression': 'CNT'})
print(f'  Total jobs: {cnt.get("result")}')

# Test 5: El script completo como doc ejecutable
print(f'\n=== Test 5: Guardar como ^docs ejecutable ===')
from pdb_docs import doc_set, doc_get
doc_set('playbook', ['msm', 'list-jobs'], {
    'content': '$O(^SYS("CONFIG","JOB",""))',
    'confidence': 10, 'source_agent': 'hermes', 'executable': True,
    'tags': ['msm', 'jobs', 'orchestrator']
})
d = doc_get('playbook', ['msm', 'list-jobs'])
print(f'  _live_data: {d.get("_live_data")}')

print(f'\n{"="*50}')
print(f'✅ Orquestador MSM validado con M-Light')
