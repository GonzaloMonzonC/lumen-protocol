"""Add bytecode caching to m_routines.py"""
lines = open('m_routines.py').readlines()

# Find the exec method and add caching
for i, line in enumerate(lines):
    if 'def exec(self, name' in line:
        for j in range(i, i+20):
            if 'vm = self.vm_class()' in lines[j]:
                indent = '        '
                cache_code = [
                    '\n',
                    f'{indent}# ── Bytecode cache (MSM: DAT_004c24e0) ──\n',
                    f'{indent}# Compila 1 vez, ejecuta N veces con datos frescos\n',
                    f'{indent}bc_key = f"BC_{name}"\n',
                    f'{indent}cached = self._load_bc(name, bc_key)\n',
                    f'{indent}if cached:\n',
                    f'{indent}    vm.instrs = cached\n',
                    f'{indent}else:\n',
                    f'{indent}    vm.compile(code)\n',
                    f'{indent}    self._save_bc(name, bc_key, vm.instrs)\n',
                    f'{indent}vm.vars["$ZTAG"] = name\n',
                    f'{indent}result = vm.exec()\n',
                ]
                # Remove the old vm.compile(code) + try/exec/return block
                lines[j] = cache_code[0]
                for k, line2 in enumerate(cache_code):
                    lines.insert(j+1+k, line2)
                break
        break

# Add save/load methods before the class ends (find __main__ guard)
for i, line in enumerate(lines):
    if "if __name__" in line:
        methods = """    def _save_bc(self, name, key, instrs):
        '''Guardar bytecode compilado en ^ROUTINE(name,key).'''
        try:
            from pdb_tools import tool_set, tool_kill
            tool_kill({"ns": "ROUTINE", "subs": [name, key]})
            for idx, inst in enumerate(instrs):
                tool_set({"ns": "ROUTINE", "subs": [name, key, str(idx)],
                         "value": f"{inst.opcode}|{inst.args}"})
            return True
        except: return False

    def _load_bc(self, name, key):
        '''Cargar bytecode cacheado desde ^ROUTINE.'''
        try:
            from pdb_tools import tool_order, tool_get
            from m_stackvm import StackOp
            instrs = []
            idx = ""
            while True:
                r = tool_order({"ns": "ROUTINE", "subs": [name, key, idx], "direction": 1})
                if not r.get("success") or r.get("value") is None: break
                idx = r["value"]
                r2 = tool_get({"ns": "ROUTINE", "subs": [name, key, idx]})
                if r2.get("success") and r2.get("value"):
                    parts = str(r2["value"]).split("|", 1)
                    if len(parts) == 2:
                        import ast
                        instrs.append(StackOp(parts[0], ast.literal_eval(parts[1])))
            return instrs if instrs else None
        except: return None

"""
        lines.insert(i, methods)
        break

open('m_routines.py', 'w').writelines(lines)
print('Added bytecode cache')
