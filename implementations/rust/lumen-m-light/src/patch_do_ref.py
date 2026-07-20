#!/usr/bin/env python3
"""Patch vm.rs: local DO .ref handling."""
import os

vm_path = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\rust\lumen-m-light\src\vm.rs'

with open(vm_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Find the old else block (lines 562-572 in original)
old_start = '        } else {\n            let arguments = split_top_level(raw_arguments, \',\')'
old_end = '        }\n        Ok(Control::Continue)\n    }\n\n    /// `LOCK'

idx_start = content.find(old_start)
idx_end = content.find(old_end, idx_start)

if idx_start < 0 or idx_end < 0:
    print('ERROR: pattern not found')
    exit(1)

old = content[idx_start:idx_end + len(old_end)]
print(f'Found else block at {idx_start}-{idx_end + len(old_end)}')

# Read the new code from a file
new_file = os.path.join(os.path.dirname(vm_path), 'local_do_ref.txt')
if not os.path.exists(new_file):
    print(f'ERROR: {new_file} not found')
    exit(1)

with open(new_file, 'r', encoding='utf-8') as f:
    new = f.read()

content = content.replace(old, new, 1)
with open(vm_path, 'w', encoding='utf-8') as f:
    f.write(content)
print('OK: vm.rs patched')
