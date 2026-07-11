"""Add label support and _exec_do to m_stackvm.py"""
lines = open('m_stackvm.py').readlines()

# 1. Add labels dict to __init__
for i, line in enumerate(lines):
    if 'self.error = None' in line and 'last' in line:
        lines.insert(i+1, '        self.labels = {}      # label → ip para DO\n')
        lines.insert(i+1, '        self.call_stack = []   # return addresses para DO\n')
        break

# 2. Replace compile method
start = end = None
for i, line in enumerate(lines):
    if 'def compile(self, code' in line:
        start = i
    elif start is not None and 'def emit(self' in line:
        end = i
        break

new_compile = """    def compile(self, code: str):
        self.instrs = []
        self.labels = {}
        self.call_stack = []
        for line in code.split('\\n'):
            line = line.strip()
            if not line or line.startswith(';'):
                continue
            # Detectar label: "LABEL ; comment" o "LABEL ;"
            # Una label es una palabra seguida de espacio, ; o final de línea
            first_word = line.split()[0] if line.split() else ""
            is_label = False
            if first_word and first_word.isidentifier() and first_word == first_word.upper():
                # No es un comando MUMPS conocido
                cmd_tokens = {"S","SET","K","KILL","F","FOR","I","IF","W","WRITE",
                             "Q","QUIT","D","DO","G","GOTO","R","READ","N","NEW",
                             "O","OPEN","C","CLOSE","U","USE","ELSE","H","HALT"}
                if first_word not in cmd_tokens:
                    is_label = True
            
            if is_label:
                # Extraer nombre de label y posible argumento
                rest = line[len(first_word):].strip()
                label_name = first_word
                if ';' in rest:
                    rest = rest.split(';')[0].strip()
                self.labels[label_name] = len(self.instrs)
                if rest:
                    # Hay código después de la label
                    token = rest.split()[0] if rest.split() else ""
                    if token.startswith("$") and "(" in token:
                        func_name = token.split("(")[0]
                        op = op_dispatch(func_name)
                        if op:
                            self.instrs.append(StackOp(op, {"rest": rest[len(func_name):].strip()}, line))
                            continue
                    op = op_dispatch(token)
                    if op:
                        self.instrs.append(StackOp(op, {"rest": rest[len(token):].strip()}, line))
                    else:
                        self.instrs.append(StackOp(OP_NOP, {"expr": rest}, line))
            else:
                # Comando normal
                token = first_word
                if token.startswith("$") and "(" in token:
                    func_name = token.split("(")[0]
                    op = op_dispatch(func_name)
                else:
                    op = op_dispatch(token)
                if op:
                    rest = line[len(token):].strip()
                    self.instrs.append(StackOp(op, {"rest": rest}, line))
                else:
                    self.instrs.append(StackOp(OP_NOP, {"expr": line}, line))
        return self
"""

lines = lines[:start] + [new_compile] + lines[end:]

# 3. Add _exec_do and _exec_goto if not present
has_do = any('def _exec_do' in l for l in lines)
if not has_do:
    # Find insertion point (before _exec_for)
    for i, line in enumerate(lines):
        if 'def _exec_kill' in line:
            do_code = """
    def _exec_do(self, rest, inst=None):
        '''DO label — llamar a subrutina con labels.'''
        rest = rest.strip()
        if not rest:
            return
        # Buscar label en este script
        label = rest.split()[0] if rest.split() else rest
        label = label.upper()
        if '(' in label:
            label = label.split('(')[0]
        if label in self.labels:
            # Guardar return address
            self.call_stack.append(self.ip)
            # Saltar a label
            self.ip = self.labels[label]
        else:
            # Intentar como rutina externa DO ^routine
            if label.startswith('^'):
                from m_routines import RoutineExecutor
                try:
                    executor = RoutineExecutor()
                    result = executor.do(rest, self)
                    if result is not None:
                        self.ops.append(result)
                except Exception as e:
                    self.ops.append(f'[DO error: {e}]')
    
    def _exec_goto(self, rest, inst=None):
        '''G label — salto incondicional.'''
        rest = rest.strip()
        if rest in self.labels:
            self.ip = self.labels[rest]

"""
            lines.insert(i, do_code)
            break

open('m_stackvm.py', 'w').writelines(lines)
print('Added labels support + _exec_do + _exec_goto')
