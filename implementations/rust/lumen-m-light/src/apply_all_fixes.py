#!/usr/bin/env python3
"""Apply ALL missing MVM fixes in one pass."""
import subprocess, sys

VM = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\rust\lumen-m-light\src\vm.rs'
HOST = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\rust\lumen-m-light\src\host.rs'
COMP = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\rust\lumen-m-light\src\compiler.rs'

# --- VM fixes ---
with open(VM, 'r', encoding='utf-8') as f:
    v = f.read()

changes = 0

# 1. [ in find_comparison pattern list
if '"["' not in v.split('for &(pattern, op) in &[list]')[0] if 'for &(pattern, op) in &[' in v else '':
    pass
old = '[(">=", ">="), ("<=", "<="), ("'+"'=, \"'="), (\"!=\", \"!=\"), (\"=\", \"=\"), (\">\", \">\"), (\"<\", \"<\")]"
new = '[(">=", ">="), ("<=", "<="), ("'+"'=, \"'="), (\"!=\", \"!=\"), (\"[\", \"[\"), (\"=\", \"=\"), (\">\", \">\"), (\"<\", \"<\")]"
if old in v:
    v = v.replace(old, new)
    changes += 1
    print(f'  + Added [ to pattern list')

# 2. [ in compare_values
old = '"<=" => !ordering.is_gt(),\n        _ => false,'
new = '"<=" => !ordering.is_gt(),\n        "[" => left.as_string().contains(&right.as_string()),\n        _ => false,'
if old in v:
    v = v.replace(old, new)
    changes += 1
    print(f'  + Added [ handler in compare_values')

# 3. ! and & in split_arithmetic
old = "op @ (b'+' | b'-' | b'*' | b'/' | b'\\\\' | b'#' | b'_') if !quoted && depth == 0 => {"
new = "op @ (b'+' | b'-' | b'*' | b'/' | b'\\\\' | b'#' | b'_' | b'!' | b'&') if !quoted && depth == 0 => {"
if old in v:
    v = v.replace(old, new)
    changes += 1
    print(f'  + Added !/& to split_arithmetic')

# 4. ! and & in apply_operator
old = 'fn apply_operator(\n    left: Value,\n    right: Value,\n    operator: char,\n    line: usize,\n) -> Result<Value, VmError> {\n    if operator == \'_\' {'
new = 'fn apply_operator(\n    left: Value,\n    right: Value,\n    operator: char,\n    line: usize,\n) -> Result<Value, VmError> {\n    if operator == \'!\' {\n        return Ok(Value::Bool(left.truthy() || right.truthy()));\n    }\n    if operator == \'&\' {\n        return Ok(Value::Bool(left.truthy() && right.truthy()));\n    }\n    if operator == \'_\' {'
if old in v:
    v = v.replace(old, new)
    changes += 1
    print(f'  + Added !/& handlers in apply_operator')

with open(VM, 'w', encoding='utf-8') as f:
    f.write(v)

# --- HOST fixes ---
with open(HOST, 'r', encoding='utf-8') as f:
    h = f.read()

# 5. Reverse $O fix
old_rev = '''        } else {
            // Retroceder: buscar \\u00faltimo key < start_key con el prefijo
            // range(..start_key) NO incluye start_key, OK
            for (k, _v) in self.values.range(..start_key).rev() {'''
new_rev = '''        } else {
            // Retroceder: buscar \\u00faltimo key con el prefijo
            // Cuando current=None, iterar desde el final del mapa
            let range: Box<dyn Iterator<Item = _>> = if current.is_some() {
                Box::new(self.values.range(..start_key).rev())
            } else {
                Box::new(self.values.range(..).rev())
            };
            for (k, _v) in range {'''

if old_rev in h:
    h = h.replace(old_rev, new_rev)
    changes += 1
    print(f'  + Fixed reverse $O')

with open(HOST, 'w', encoding='utf-8') as f:
    f.write(h)

# --- COMPILER fixes ---
with open(COMP, 'r', encoding='utf-8') as f:
    c = f.read()

# 6. FOR always consumes all remaining text
old = '        let boundary = if has_no_argument || is_quit_no_arg {\n            0\n        } else if consumes_remainder {\n            after_token.len()\n        } else {\n            next_command_boundary(after_token)\n        };'
new = '        let boundary = if has_no_argument || is_quit_no_arg {\n            0\n        } else if matches!(command, Opcode::For) || consumes_remainder {\n            after_token.len()\n        } else {\n            next_command_boundary(after_token)\n        };'
if old in c:
    c = c.replace(old, new)
    changes += 1
    print(f'  + Forced FOR to consume all text')

with open(COMP, 'w', encoding='utf-8') as f:
    f.write(c)

print(f'\\nTotal changes: {changes}')
if changes > 0:
    print('\\nBuilding...')
    r = subprocess.run(['cargo', 'build', '--release'], 
                       cwd=r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\rust\lumen-m-light',
                       capture_output=True, text=True)
    if r.returncode == 0:
        print('  Build OK')
    else:
        print('  BUILD ERRORS:')
        print(r.stderr[-500:])
