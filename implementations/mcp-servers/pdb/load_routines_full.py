"""Cargar rutinas MSM desde RUTS110626.RUT a ^ROUTINE."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdb_tools import tool_set

FILE = "C:/msm/RUTS110626.RUT"

with open(FILE, 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()

routines = {}
current = None
for line in lines:
    s = line.rstrip('\n\r')
    if not s:
        if current: routines[current] = routines.get(current, [])
        current = None; continue
    if s and s[0] not in (' ', '\t', ';') and current is None:
        name = s.split()[0] if s.split() else s
        current = name
        routines[current] = routines.get(current, [])
    elif current:
        routines[current].append(s.strip())

print(f"📂 {len(routines)} rutinas encontradas")

# Cargar TODAS a ^ROUTINE
targets = ['JRNL','DEJRNL','DEJRNL1','DEJRNL2','DEJRNL3','DEJRNDDP','JRNXDDP',
           'DDP','DDPCIR','DDPCON','DDPCON2','DDPLNK','DDPSECU','DDPADV',
           'SGDDP','SGDDP2','SGDDP3','SGDDP4','SGDDPL','SGDDPNT','SGDDPOMI',
           'MAPDDP','MAPJRNL','JRNLPRT','JRNLPRT2','JRNLSHOW','STUDDP',
           '%DBSYNC','MSADDP']
loaded = 0
for name in targets:
    if name in routines:
        for i, code in enumerate(routines[name]):
            tool_set({'ns':'ROUTINE','subs':[name,i+1],'value':code})
        loaded += 1
        print(f"  ✅ {name:15s} {len(routines[name]):4d} líneas")
    else:
        print(f"  ❌ {name:15s} NOT FOUND")

# Index
for name in targets:
    if name in routines:
        tool_set({'ns':'ROUTINE','subs':['INDEX',name],'value':''})

print(f"\n💾 {loaded} rutinas cargadas en ^ROUTINE")
