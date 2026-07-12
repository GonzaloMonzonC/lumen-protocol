"""Replace _save_bc and _load_bc with checksum support"""
lines = open('m_routines.py').readlines()

# Find _save_bc and replace
for i, line in enumerate(lines):
    if 'def _save_bc(self, name, key, instrs):' in line:
        lines[i] = '    def _save_bc(self, name, key, instrs, code=""):\n'
        lines[i+1] = "        '''Guardar bytecode + checksum SHA256 del source.'''\n"
        # Insert checksum line after tool_kill
        for j in range(i, i+10):
            if 'tool_kill' in lines[j]:
                lines.insert(j+1, '            import hashlib\n')
                lines.insert(j+2, '            cs = hashlib.sha256(code.encode()).hexdigest()[:16]\n')
                lines.insert(j+3, '            tool_set({"ns": "ROUTINE", "subs": [name, key, "_cs"], "value": cs})\n')
                break
        break

# Find _load_bc and replace
for i, line in enumerate(lines):
    if 'def _load_bc(self, name, key):' in line:
        lines[i] = '    def _load_bc(self, name, key, code=""):\n'
        lines[i+1] = "        '''Cargar bytecode si source no ha cambiado.'''\n"
        # Insert checksum verification after imports
        for j in range(i, i+15):
            if 'from m_stackvm import StackOp' in lines[j]:
                lines.insert(j+1, '            import hashlib\n')
                lines.insert(j+2, '            r_cs = tool_get({"ns": "ROUTINE", "subs": [name, key, "_cs"]})\n')
                lines.insert(j+3, '            if r_cs.get("success") and r_cs.get("value"):\n')
                lines.insert(j+4, '                current_cs = hashlib.sha256(code.encode()).hexdigest()[:16]\n')
                lines.insert(j+5, '                if r_cs["value"] != current_cs:\n')
                lines.insert(j+6, '                    return None  # source changed, recompile\n')
                lines.insert(j+7, '            else:\n')
                lines.insert(j+8, '                return None  # no cache\n')
                break
        break

open('m_routines.py', 'w').writelines(lines)
print('Added checksum invalidation to BC cache')
