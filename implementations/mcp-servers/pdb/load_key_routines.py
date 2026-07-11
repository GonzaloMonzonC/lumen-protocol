"""Cargar rutinas MSM clave a PDB (DDP, DEJRNL, MAP, %DBSYNC)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdb_tools import tool_set

targets = {'DDP':False,'DEJRNL':False,'MAPJRNL':False,'MAPDDP':False,'%DBSYNC':False}
current = None; lines_buf = []; total = 0

with open('C:/msm/RUTS110626.RUT','r',encoding='utf-8',errors='replace') as f:
    for line in f:
        s = line.rstrip('\n\r')
        if not s:
            if current in targets:
                for i, code in enumerate(lines_buf,1):
                    tool_set({'ns':'ROUTINE','subs':[current,i],'value':code})
                tool_set({'ns':'ROUTINE','subs':['INDEX',current],'value':''})
                targets[current] = True; total += 1
            current = None; lines_buf = []
            continue
        if s and s[0] not in (' \t;') and current is None:
            current = s.split()[0] if s.split() else s
        elif current in targets:
            lines_buf.append(s.strip())

for name, found in targets.items():
    print(f"  {'OK' if found else 'MISS'} {name}")
print(f"Total: {total} rutinas")
