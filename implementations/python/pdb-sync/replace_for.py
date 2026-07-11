"""Replace _exec_for in m_stackvm.py"""
lines = open('m_stackvm.py').readlines()

start = None; end = None
for i, line in enumerate(lines):
    if 'def _exec_for(self, rest' in line:
        start = i
    elif start is not None and i > start and 'def _exec_kill' in line:
        end = i; break

new_method = """    def _exec_for(self, rest, inst=None):
        if not rest: return
        if '=' in rest and '$O' in rest:
            self._exec_for_order(rest); return
        if '=' in rest:
            var, _, rest2 = rest.partition('=')
            var = var.strip()
            rp = rest2.split(None, 1)[0] if rest2.split() else ''
            body = rest2[len(rp):].strip() if len(rest2) > len(rp) else ''
            parts = rp.split(':')
            start = self._eval_expr(parts[0]) if parts[0] else 1
            step = self._eval_expr(parts[1]) if len(parts) > 1 and parts[1] else 1
            limit = self._eval_expr(parts[2]) if len(parts) > 2 and parts[2] else None
            i = int(start)
            while limit is None or i <= int(limit):
                self.vars[var] = i
                if body:
                    vm2 = __import__('m_stackvm', fromlist=['StackVM']).StackVM()
                    vm2.vars = self.vars; vm2.compile(body).exec()
                    self.vars = vm2.vars
                    if vm2.quit_flag: break
                i += int(step)

    def _exec_for_order(self, rest):
        var = rest.split('=')[0].replace('S','').strip() if '=' in rest else 'x'
        ref = ''
        if '$O' in rest:
            after = rest.split('$O',1)[1]
            depth = 0
            for i,ch in enumerate(after):
                if ch == '(': depth += 1
                elif ch == ')': depth -= 1
                if depth == 0: ref = after[:i+1]; break
        if not ref: return
        from m_funcs import eval_function
        key = ''
        while True:
            result = eval_function('$O', ref.replace('""', '"' + key + '"'))
            if not result: break
            self.vars[var] = result; self.ops.append(result)
            key = result
            if 'Q:' in rest:
                cond = rest.split('Q:',1)[1].strip()
                if cond:
                    val = self._eval_expr(cond)
                    if val: break

"""

lines = lines[:start] + [new_method] + lines[end:]
open('m_stackvm.py', 'w').writelines(lines)
print(f'Replaced _exec_for at lines {start}-{end}')
