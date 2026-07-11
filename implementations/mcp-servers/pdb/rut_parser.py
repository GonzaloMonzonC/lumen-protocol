#!/usr/bin/env python3
"""
rut_parser.py — Parser de ficheros RUT (routine save) de MSM.

Formato:
  Linea 1: timestamp (cabecera)
  Linea 2: en blanco
  Para cada rutina:
    Nombre (una linea)
    Lineas de codigo (nombre+espacio+;comentario o codigo)
    Labels (word+; en linea propia)
  Separador: linea en blanco + nombre

Uso: python rut_parser.py C:/msm/MGR301208.RUT [--list|--search|--categories]
"""

import re, sys, os
from collections import defaultdict

class RUTParser:
    def __init__(self, filepath):
        self.filepath = filepath
        self.routines = {}  # name -> [lines]
        self._parse()

    def _parse(self):
        with open(self.filepath, 'r', encoding='utf-8', errors='replace') as f:
            raw = f.read()

        lines = raw.split('\n')
        i = 0
        
        # Skip header
        while i < len(lines) and (not lines[i].strip() or ':' in lines[i] or lines[i].strip().startswith('Copy')):
            i += 1

        current_routine = None
        current_lines = []

        while i < len(lines):
            line = lines[i]
            stripped = line.rstrip('\r')

            # Skip blank lines
            if not stripped:
                # End current routine
                if current_routine:
                    self.routines[current_routine] = current_lines
                    current_routine = None
                    current_lines = []
                i += 1
                continue

            # Check if this is a new routine name (word at start, no leading space)
            if stripped[0] not in (' ', '\t', ';'):
                # Could be a label or routine name
                # Check PREVIOUS line was blank OR this is start of file
                prev_blank = (i == 0) or (i > 0 and not lines[i-1].strip())
                
                if prev_blank:
                    # New routine!
                    if current_routine:
                        self.routines[current_routine] = current_lines
                    current_routine = stripped.split()[0] if stripped.split() else stripped
                    current_lines = []
                else:
                    # Label within current routine
                    if current_routine:
                        current_lines.append(stripped)
            else:
                # Continuation line
                if current_routine:
                    current_lines.append(stripped)

            i += 1

        # Last routine
        if current_routine:
            self.routines[current_routine] = current_lines

    def get_routine(self, name):
        return self.routines.get(name, [])

    def list_routines(self, sort_by='name'):
        items = list(self.routines.items())
        if sort_by == 'size':
            items.sort(key=lambda x: len(x[1]), reverse=True)
        else:
            items.sort(key=lambda x: x[0])
        return items

    def categorize(self):
        cats = defaultdict(list)
        for name, lines in self.routines.items():
            first_line = lines[0] if lines else ''
            hdr = first_line.split(';')[1].strip() if ';' in first_line else ''
            code = '\n'.join(lines)
            
            if re.search(r'\bJRNL|JOURNAL|DEJRNL\b', code, re.I): cats['JRNL'].append(name)
            if re.search(r'\bDDP|NETWORK|LINK|CIRCUIT\b', code, re.I): cats['DDP'].append(name)
            if re.search(r'\bDEVICE|TERMINAL|PRINTER|TAPE\b', code, re.I): cats['DEVICE'].append(name)
            if re.search(r'\bLOCK|DEADLOCK\b', code, re.I): cats['LOCK'].append(name)
            if re.search(r'\bERROR|TRAP|DSCON\b', code, re.I): cats['ERROR'].append(name)
            if re.search(r'\bCONFIG|SYSTEM|INIT|STARTUP\b', code, re.I): cats['CONFIG'].append(name)
            if re.search(r'\bGLOBAL|^%G', name): cats['GLOBAL'].append(name)
            if re.search(r'\bJOB|PARTITION|PROCESS\b', code, re.I): cats['JOB'].append(name)
            if re.search(r'\b%ZS|%ZM|%ZE|%ZH|%ZR|%ZC\b', code, re.I): cats['Z-FUNC'].append(name)
        return cats

    def total_lines(self):
        return sum(len(lines) for lines in self.routines.values())

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Uso: python rut_parser.py <file.rut> [--list|--search|--categories|--info <name>]")
        sys.exit(1)

    filepath = sys.argv[1]
    parser = RUTParser(filepath)
    cmd = sys.argv[2] if len(sys.argv) > 2 else '--info'

    if cmd == '--list':
        for name, lines in parser.list_routines():
            first = lines[0][:60] if lines else '(empty)'
            print(f"  {name:20s} {len(lines):4d} líneas  {first}")

    elif cmd == '--search':
        query = sys.argv[3] if len(sys.argv) > 3 else ''
        for name, lines in parser.list_routines():
            code = '\n'.join(lines)
            if query.upper() in code.upper():
                print(f"  {name:20s} {len(lines):4d} líneas — contiene '{query}'")

    elif cmd == '--categories':
        cats = parser.categorize()
        for cat, items in sorted(cats.items()):
            print(f"\n{cat}: ({len(items)} rutinas)")
            for name in items:
                lines = parser.get_routine(name)
                print(f"  {name:20s} {len(lines):4d} líneas")

    elif cmd == '--info':
        name = sys.argv[3] if len(sys.argv) > 3 else ''
        if name:
            lines = parser.get_routine(name)
            print(f"{name}: {len(lines)} líneas")
            for i, line in enumerate(lines[:20], 1):
                print(f"  {i:2d}: {line[:100]}")
        else:
            print(f"📊 {filepath}")
            print(f"   Total rutinas: {len(parser.routines)}")
            print(f"   Total líneas:  {parser.total_lines()}")
            cats = parser.categorize()
            for cat, items in sorted(cats.items()):
                print(f"   {cat}: {len(items)} rutinas -> {', '.join(items[:5])}{'...' if len(items)>5 else ''}")
