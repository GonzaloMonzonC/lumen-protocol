"""Cargar ^SYS, ^HELP, ^JOURNAL desde GS110726.GS a PDB."""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
from pdb_tools import tool_set

FILE = "C:/msm/GS110726.GS"
TARGETS = {'SYS', 'JOURNAL', 'HELP', 'SYSGEN', 'DDP', 'DEJRNL', 'GWPARAM'}

with open(FILE, 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()

current = None
count = 0
for line in lines:
    s = line.rstrip('\n\r')
    if not s: continue
    m = re.match(r'\^(\w+)\(?(.*?)\)?$', s)
    if m and s.startswith('^') and not s.startswith('^%'):
        gname = m.group(1)
        if gname not in TARGETS:
            current = None; continue
        subs_str = m.group(2)
        subs = [x.strip().strip('"') for x in subs_str.split(',')] if subs_str else []
        current = gname; current_subs = subs
        continue
    if current and s and not s.startswith('^'):
        full_subs = current_subs + [s]
        tool_set({'ns': current, 'subs': full_subs, 'value': s})
        count += 1

print(f"💾 {count} entradas de {sorted(TARGETS)}")
