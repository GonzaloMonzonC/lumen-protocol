"""Strings analysis of msm.exe."""
import re

with open('C:/msm/msm.exe', 'rb') as f:
    data = f.read()

strings = re.findall(rb'[\x20-\x7e]{4,}', data)

funcs = set()
errors = set()
files = set()
dlls = set()
globals_ = set()
compiler = set()

for s in strings:
    t = s.decode('ascii', errors='replace')
    if t.startswith('_') or t.startswith('@'):
        funcs.add(t)
    elif 'error' in t.lower() or 'fail' in t.lower():
        errors.add(t)
    elif '.dll' in t.lower():
        dlls.add(t)
    elif t.startswith('^'):
        globals_.add(t)
    elif 'Microsoft' in t or 'C++' in t or 'Visual' in t:
        compiler.add(t)

print(f'Total: {len(strings)} strings')
print(f'\nFUNCIONES ({len(funcs)}):')
for s in sorted(funcs)[:40]: print(f'  {s}')

print(f'\nERRORES ({len(errors)}):')
for s in sorted(errors)[:20]: print(f'  {s}')

print(f'\nDLLs ({len(dlls)}):')
for s in sorted(dlls)[:15]: print(f'  {s}')

print(f'\nGLOBALS ({len(globals_)}):')
for s in sorted(globals_)[:15]: print(f'  {s}')

print(f'\nCOMPILADOR ({len(compiler)}):')
for s in sorted(compiler)[:10]: print(f'  {s}')
