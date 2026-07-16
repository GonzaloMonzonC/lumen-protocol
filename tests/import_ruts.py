#!/usr/bin/env python3
"""Parse .RUT files and import routines into PDB."""
import sys, os

def parse_rut(path):
    with open(path, 'r', encoding='latin-1') as f:
        lines = f.readlines()
    routines = {}
    current_name = None
    current_code = []
    for line in lines:
        stripped = line.rstrip('\n\r ')
        if stripped and (stripped[0].isalpha() or stripped[0] == '%'):
            parts = stripped.split(None, 1)
            if parts and parts[0].isupper() and len(parts[0]) <= 32:
                name = parts[0].replace('^', '')
                if current_name and current_code:
                    routines[current_name] = '\n'.join(current_code)
                current_name = name
                current_code = [stripped]
                continue
        if current_name:
            current_code.append(stripped)
    if current_name and current_code:
        routines[current_name] = '\n'.join(current_code)
    return routines

def import_to_pdb(routines):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'implementations', 'python', 'pdb-sync'))
    os.chdir(os.path.join(os.path.dirname(__file__), '..', 'implementations', 'python', 'pdb-sync'))
    sys.path.insert(0, '.')
    import _paths
    from pdb_tools import tool_set
    
    count = 0
    for name, code in sorted(routines.items()):
        try:
            lines = code.split('\n')
            for i, line in enumerate(lines, 1):
                tool_set({'ns': 'ROUTINE', 'subs': [name, str(float(i))], 'value': line})
            tool_set({'ns': 'ROUTINE', 'subs': [name], 'value': float(len(lines))})
            count += 1
            if count % 200 == 0:
                print(f'  {count} imported...')
        except Exception as e:
            pass  # skip problematic routines
    return count

if __name__ == '__main__':
    path = sys.argv[1]
    print(f'Parsing {path}...')
    routines = parse_rut(path)
    print(f'Found {len(routines)} routines')
    for name in sorted(routines, key=lambda n: -len(routines[n]))[:5]:
        print(f'  {name}: {len(routines[name])} chars')
    if '--import' in sys.argv:
        print('Importing...')
        ok = import_to_pdb(routines)
        print(f'Imported: {ok}')
