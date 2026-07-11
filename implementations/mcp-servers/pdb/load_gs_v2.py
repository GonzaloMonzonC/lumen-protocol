"""Cargar ^SYS, ^HELP desde GS110726.GS — formato corregido."""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
from pdb_tools import tool_set

FILE = "C:/msm/GS110726.GS"

with open(FILE, 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()

current_ns = None
current_subs = None
value_lines = []
count = 0

for line in lines:
    s = line.rstrip('\n\r')
    # Saltar header y vacíos
    if not s or 'PM' in s or 'AM' in s:
        continue

    # Detectar ^GLOBAL o ^GLOBAL(subs)
    if s.startswith('^'):
        # Guardar el anterior si había
        if current_ns and value_lines:
            full_subs = current_subs if current_subs else []
            val = '\n'.join(value_lines) if len(value_lines) > 1 else value_lines[0]
            if current_ns in ('SYS','HELP','JOURNAL','DDP','DEJRNL','GWPARAM','SYSGEN','ZMSMSRC'):
                tool_set({'ns': current_ns, 'subs': full_subs, 'value': val})
                count += 1

        # Parsear nuevo global
        m = re.match(r'\^(\w+)\(?(.*?)\)?$', s)
        if m:
            current_ns = m.group(1)
            subs_str = m.group(2)
            if subs_str:
                # Parsear subíndices: "0,\"AUTO\",\"JRNL\""
                parts = []
                depth = 0; current = ''
                for ch in subs_str:
                    if ch == '"': depth ^= 1
                    elif ch == ',' and depth == 0:
                        parts.append(current.strip().strip('"'))
                        current = ''
                        continue
                    current += ch
                if current: parts.append(current.strip().strip('"'))
                current_subs = parts
            else:
                current_subs = []
            value_lines = []
        else:
            current_ns = None
    else:
        # Línea de valor (puede ser código MUMPS)
        if current_ns:
            value_lines.append(s.strip())

# Último global
if current_ns and value_lines:
    full_subs = current_subs if current_subs else []
    val = '\n'.join(value_lines) if len(value_lines) > 1 else value_lines[0]
    if current_ns in ('SYS','HELP','JOURNAL','DDP','DEJRNL','GWPARAM','SYSGEN','ZMSMSRC'):
        tool_set({'ns': current_ns, 'subs': full_subs, 'value': val})
        count += 1

print(f"💾 {count} entradas cargadas")
