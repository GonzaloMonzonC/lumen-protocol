"""Add bytecode cache to RoutineExecutor class."""

lines = open('m_routines.py').readlines()

# 1. Replace the vm.compile(code) + try block in exec()
for i, line in enumerate(lines):
    if 'vm.compile(code)' in line:
        lines[i] = '        # ── Bytecode cache ──\n'
        lines.insert(i+1, '        bc_key = f"BC_{name}"\n')
        lines.insert(i+2, '        cached = self._load_bc(name, bc_key, code)\n')
        lines.insert(i+3, '        if cached:\n')
        lines.insert(i+4, '            vm.instrs = cached\n')
        lines.insert(i+5, '        else:\n')
        lines.insert(i+6, '            vm.compile(code)\n')
        lines.insert(i+7, '            self._save_bc(name, bc_key, vm.instrs, code)\n')
        lines.insert(i+8, '        \n')
        lines.insert(i+9, '        vm.vars["$ZTAG"] = name\n')
        lines.insert(i+10, '        \n')
        lines.insert(i+11, '        # Ejecutar\n')
        break

# 2. Add _save_bc and _load_bc methods before CLI section
for i, line in enumerate(lines):
    if '# ── CLI ──' in line:
        methods = '''
    def _save_bc(self, name, key, instrs, code=""):
        try:
            from pdb_tools import tool_set, tool_kill
            import hashlib
            tool_kill({"ns": "ROUTINE", "subs": [name, key]})
            cs = hashlib.sha256(code.encode()).hexdigest()[:16]
            tool_set({"ns": "ROUTINE", "subs": [name, key, "_cs"], "value": cs})
            for idx, inst in enumerate(instrs):
                tool_set({"ns": "ROUTINE", "subs": [name, key, str(idx)],
                         "value": f"{inst.opcode}|{inst.args}"})
            return True
        except: return False

    def _load_bc(self, name, key, code=""):
        try:
            from pdb_tools import tool_order, tool_get
            from m_stackvm import StackOp
            import hashlib
            r_cs = tool_get({"ns": "ROUTINE", "subs": [name, key, "_cs"]})
            if r_cs.get("success") and r_cs.get("value"):
                current_cs = hashlib.sha256(code.encode()).hexdigest()[:16]
                if r_cs["value"] != current_cs: return None
            else: return None
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
'''
        lines.insert(i, methods)
        break

open('m_routines.py', 'w').writelines(lines)
print('Added cache methods + exec integration')
