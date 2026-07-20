#!/usr/bin/env python3
"""Apply permanent MVM fixes (no debugs)."""
import os

VM = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\rust\lumen-m-light\src\vm.rs'
HOST = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\rust\lumen-m-light\src\host.rs'

# Fix 1: split_for_body - detect command names
with open(VM, 'r', encoding='utf-8') as f:
    v = f.read()

# Already applied via revert? Check if fix is present
if 'is_command_name(first_token)' not in v:
    old = 'fn split_for_body(value: &str) -> (&str, &str) {\n    let mut depth = 0i32;'
    new = 'fn split_for_body(value: &str) -> (&str, &str) {\n    let trimmed = value.trim();\n    if let Some(space) = trimmed.find(char::is_whitespace) {\n        let first_token = &trimmed[..space];\n        if is_command_name(first_token) {\n            return ("", trimmed);\n        }\n    }\n    let mut depth = 0i32;'
    v = v.replace(old, new)

# Fix 2: exec_do trim_start
old = "fn exec_do(&mut self, argument: &str, line: usize) -> Result<Control, VmError> {\n        // find first space outside parens/quotes (smart split for strings)"
new = "fn exec_do(&mut self, argument: &str, line: usize) -> Result<Control, VmError> {\n        let argument = argument.trim_start();\n        // find first space outside parens/quotes (smart split for strings)"
if old in v:
    v = v.replace(old, new)

# Fix 3: exec_do command inline execution  
old = '        // DO followed by another M command is a block marker, not a routine call\n        if is_command_name(target_name) {\n            return Ok(Control::Continue);\n        }'
new = '        // DO followed by another M command — could be block marker (skip) or same-line continuation\n        if is_command_name(target_name) {\n            let original_arg = argument.trim();\n            if original_arg.len() > target_name.len() {\n                let after = &original_arg[target_name.len()..].trim();\n                if !after.is_empty() {\n                    return self.exec_inline_control(original_arg, line);\n                }\n            }\n            return Ok(Control::Continue);\n        }'
if old in v:
    v = v.replace(old, new)

# Fix 4: exec_do dot block marker (never-mind, empty dots skip)
old = '        // Block marker with . (FOR DO continuation) — skip\n        if target_name.starts_with(\'.\') {\n            return Ok(Control::Continue);\n        }'
new = '        // Block marker with . — skip (content already in flat compiled body)\n        if target_name.starts_with(\'.\') {\n            return Ok(Control::Continue);\n        }'
if old in v:
    v = v.replace(old, new)

with open(VM, 'w', encoding='utf-8') as f:
    f.write(v)

# Fix 5: host.rs reverse $O fix
with open(HOST, 'r', encoding='utf-8') as f:
    h = f.read()

old_rev = '''        } else {
            // Retroceder: buscar último key < start_key con el prefijo
            // range(..start_key) NO incluye start_key, OK
            for (k, _v) in self.values.range(..start_key).rev() {'''
new_rev = '''        } else {
            // Retroceder: buscar último key con el prefijo
            // Cuando current=None, iterar desde el final del mapa
            let range: Box<dyn Iterator<Item = _>> = if current.is_some() {
                Box::new(self.values.range(..start_key).rev())
            } else {
                Box::new(self.values.range(..).rev())
            };
            for (k, _v) in range {'''

if old_rev in h:
    h = h.replace(old_rev, new_rev)
    with open(HOST, 'w', encoding='utf-8') as f:
        f.write(h)

print('Fixes applied. Verifying...')

# Verify
with open(VM, 'r') as f:
    c = f.read()
checks = [
    ('split_for_body command fix', 'is_command_name(first_token)' in c),
    ('exec_do trim_start fix', 'let argument = argument.trim_start();' in c),
    ('exec_do inline execution fix', 'exec_inline_control(original_arg, line)' in c),
]
for name, ok in checks:
    print(f'  {"✅" if ok else "❌"} {name}')

with open(HOST, 'r') as f:
    h = f.read()
rev_fixed = 'Box::new(self.values.range(..).rev())' in h
print(f'  {"✅" if rev_fixed else "❌"} reverse $O fix')

print('\nAll fixes applied.')
