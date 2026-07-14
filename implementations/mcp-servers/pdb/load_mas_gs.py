"""Cargar ^%HELP y ^%MSA de mas.GS a PDB."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdb_tools import tool_set

lines = open('C:/msm/mas.GS', 'r', encoding='utf-8', errors='replace').readlines()

def parse_gs(lines, name):
    entries = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(f'^{name}('):
            m = re.match(rf'\^{name}\((.*)\)', line)
            if m:
                subs_str = m.group(1)
                subs = []
                cur = ''
                in_q = False
                for ch in subs_str:
                    if ch == '"': in_q = not in_q; cur += ch
                    elif ch == ',' and not in_q:
                        s = cur.strip().strip('"')
                        try: subs.append(int(s))
                        except: subs.append(s)
                        cur = ''
                    else: cur += ch
                if cur.strip():
                    s = cur.strip().strip('"')
                    try: subs.append(int(s))
                    except: subs.append(s)
                if i + 1 < len(lines):
                    val = lines[i+1].rstrip('\n\r ')
                    entries.append({'subs': subs, 'value': val})
                i += 2
                continue
        elif line.startswith('^') and not line.startswith(f'^{name}('):
            if entries: break
        i += 1
    return entries

help_e = parse_gs(lines, '%HELP')
msa_e = parse_gs(lines, '%MSA')

for e in help_e:
    tool_set({'ns': 'System', 'subs': ['help'] + e['subs'], 'value': e['value']})
for e in msa_e:
    tool_set({'ns': 'System', 'subs': ['services'] + e['subs'], 'value': e['value']})

print(f"✅ ^%HELP → System(help): {len(help_e)} entries")
print(f"✅  ^%MSA → System(services): {len(msa_e)} entries")

if help_e:
    print(f"\n📖 ^%HELP (jerarquía):")
    for e in help_e[:8]:
        print(f"  {e['subs']} = {str(e['value'])[:70]}")
if msa_e:
    print(f"\n🗂️ ^%MSA (service registry):")
    for e in msa_e[:10]:
        print(f"  {e['subs']} = {str(e['value'])[:70]}")
