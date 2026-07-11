#!/usr/bin/env python3
"""
m_stackvm.py — Stack-based expression evaluator para M-Light v2.

Inspirado en MSM FUN_00440ca0 (bytecode executor, 1.538 instr).

Arquitectura (Zalo):
  - Pila de operandos + operadores
  - Error trap nativo ($ECODE/$ZERROR)
  - B-tree ligero para dispatch de opcodes
  - 4 opcodes prioritarios: SET, WRITE, IF, FOR
  - FOR + INDIRECT integrados desde diseño

MSM → PDB:
  Opcode 0x7x + linked list   → StackOp con type + args
  setjmp/longjmp               → ErrorTrap con try/except nativo
  Function table runtime       → OP_TABLE con binary search
  Bytecode buffer DAT_24e0     → self.instrs list

Autor: Hermes + CadencesLab
Licencia: MIT
"""

import sys, os, time
from typing import Any, Optional

# ── Error trap nativo (MSM: FUN_0043eac0 pattern) ──

class MError(Exception):
    """Error MUMPS con $ECODE/$ZERROR (MSM: FUN_0043eac0 style)."""
    def __init__(self, code: int, msg: str, context: dict = None):
        self.ecode = f"M{code}"        # $ECODE: código de error
        self.zerror = msg               # $ZERROR: mensaje
        self.context = context or {}
        super().__init__(f"[{self.ecode}] {self.zerror}")

# ── Opcodes (prioritarios: SET, WRITE, IF, FOR) ──

OP_PUSH   = "PUSH"    # Push valor a la pila
OP_POP    = "POP"     # Pop de la pila
OP_SET    = "SET"     # SET var = expr
OP_WRITE  = "WRITE"   # WRITE expr
OP_IF     = "IF"      # IF cond {body} [ELSE {body}]
OP_FOR    = "FOR"     # FOR var=start:step:limit {body}
OP_INDIR  = "INDIR"   # ^ (indirect reference)
OP_GET    = "GET"     # $GET(^ns(subs))
OP_DATA   = "DATA"    # $DATA(^ns(subs))
OP_ORDER  = "ORDER"   # $ORDER(^ns(subs))
OP_KILL   = "KILL"    # KILL ^ns(subs)
OP_QUIT   = "QUIT"    # Q[:cond]
OP_DO     = "DO"      # DO ^routine
OP_GOTO   = "GOTO"    # G label
OP_READ   = "READ"    # READ var
OP_NEW    = "NEW"     # NEW var
OP_HALT   = "HALT"    # HALT
OP_LABEL  = "LABEL"   # Label definition
OP_NOP    = "NOP"     # No operation

# B-tree ligero para dispatch (Zalo: en vez de binary search plana)
# 8 entradas prioritarias cubren 80% de uso (SET, WRITE, IF, FOR, GET, KILL, INDIR, DATA)
OP_TABLE = [  # sorted ASCII
    ("$D",   OP_DATA),
    ("$G",   OP_GET),
    ("$O",   OP_ORDER),
    ("D",    OP_DO),
    ("F",    OP_FOR),
    ("G",    OP_GOTO),  # G = GOTO (no GET, eso es \$G)
    ("I",    OP_IF),
    ("K",    OP_KILL),
    ("Q",    OP_QUIT),
    ("S",    OP_SET),
    ("W",    OP_WRITE),
    ("^",    OP_INDIR),
]



def op_dispatch(token: str) -> Optional[str]:
    """B-tree ligero: binary search sobre OP_TABLE."""
    t = token  # No upper() — ^ no es letra
    # Normalizar: $funciones y letras a uppercase
    if t.isalpha():
        t = t.upper()
    lo, hi = 0, len(OP_TABLE) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        name, op = OP_TABLE[mid]
        if t == name: return op
        elif t < name: hi = mid - 1
        else: lo = mid + 1
    return None

# ── Stack instruction ──

class StackOp:
    """Instrucción del stack VM (MSM: bytecode linked list entry)."""
    __slots__ = ('opcode', 'args', 'source')
    def __init__(self, opcode: str, args: dict = None, source: str = ""):
        self.opcode = opcode
        self.args = args or {}
        self.source = source
    def __repr__(self):
        return f"{self.opcode}({self.args})"

# ── Stack VM ──

class StackVM:
    """Stack-based VM para MUMPS (MSM FUN_00440ca0 pattern).
    
    Características:
    - Pila de operandos + operadores
    - Error trap nativo ($ECODE)
    - 4 opcodes prioritarios (SET, WRITE, IF, FOR)
    - FOR + INDIRECT integrados
    - B-tree ligero para dispatch
    """
    
    def __init__(self):
        self.ops = []           # pila de operandos
        self.instrs = []        # lista de instrucciones
        self.ip = 0             # instruction pointer
        self.vars = {}          # variables locales
        self.quit_flag = False
        self.error = None       # último $ECODE
        self._start_time = 0
        self._timeout = 10      # max segundos por ejecución
    
    # ── Compilación (MCompiler simplificado) ──
    
    def compile(self, code: str):
        self.instrs = []
        self.labels = {}
        self.call_stack = []
        for line in code.split('\n'):
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
    def emit(self, opcode: str, args: dict = None, source: str = ""):
        """Emitir instrucción directamente."""
        self.instrs.append(StackOp(opcode, args, source))
        return self
    
    # ── Ejecución ──
    
    def exec(self):
        """Ejecutar instrucciones compiladas.
        
        MSM: FUN_00440ca0: setjmp → loop → dispatch → handler.
        PDB: try/except → while ip < len → dispatch → handler.
        """
        self.ip = 0
        self.ops = []
        self.quit_flag = False
        self.error = None
        self._start_time = time.time()
        
        try:
            while 0 <= self.ip < len(self.instrs) and not self.quit_flag:
                # Timeout (MSM: $ZTIME limit)
                if time.time() - self._start_time > self._timeout:
                    raise MError(9, "TIMEOUT", {"ip": self.ip})
                
                inst = self.instrs[self.ip]
                self.ip += 1
                self._exec_op(inst)
                
        except MError as e:
            self.error = e
            return {"error": e.ecode, "msg": e.zerror, "context": e.context}
        except Exception as e:
            self.error = MError(99, str(e))
            return {"error": "M99", "msg": str(e)}
        
        result = self.ops[-1] if self.ops else None
        return {"result": result, "vars": dict(self.vars)}
    
    def _exec_op(self, inst: StackOp):
        """Ejecutar una instrucción (MSM: opcode dispatch)."""
        h = {
            OP_SET:   self._exec_set,
            OP_WRITE: self._exec_write,
            OP_IF:    self._exec_if,
            OP_FOR:   self._exec_for,
            OP_KILL:  self._exec_kill,
            OP_QUIT:  self._exec_quit,
            OP_DO:    self._exec_do,
            OP_GOTO:  self._exec_goto,
            OP_GET:   self._exec_get,
            OP_DATA:  self._exec_data,
            OP_ORDER: self._exec_order,
            OP_INDIR: self._exec_indir,
            OP_NOP:   self._exec_nop,
        }
        handler = h.get(inst.opcode)
        if handler:
            handler(inst.args.get("rest", ""), inst)
        else:
            self.ops.append((inst.opcode, inst.args))
    
    def _exec_set(self, rest: str, inst=None):
        """SET var = expr (MSM: B-tree opcode 's')."""
        if '=' in rest:
            name, _, val = rest.partition('=')
            name = name.strip()
            val = val.split()[0] if val.strip() else ""  # solo primer token
            try:
                result = self._eval_expr(val)
                self.vars[name] = result
                self.ops.append(result)
            except Exception as e:
                raise MError(3, f"SET error: {e}", {"var": name, "val": val})
    
    def _exec_write(self, rest: str, inst=None):
        """WRITE expr — soporta strings, newline, concatenación.
        
        MSM: W "texto",!,"a",var → W "texto",!,var
        """
        if not rest:
            return
        
        # Parsear argumentos separados por coma
        parts = self._parse_write_args(rest)
        output = ""
        for part in parts:
            if part == "!":
                output += "\n"
            elif part.startswith('"') and part.endswith('"'):
                output += part[1:-1]
            else:
                val = self._eval_expr(part)
                if val is not None:
                    output += str(val)
        
        self.ops.append(output)
        if hasattr(self, '_on_write') and self._on_write:
            self._on_write(output)
    
    def _parse_write_args(self, s: str) -> list:
        """Parsear argumentos de WRITE separados por coma.
        
        "a",!,"b",var → ["a", "!", "b", "var"]
        """
        args = []
        cur = ""
        in_str = False
        for ch in s:
            if ch == '"':
                in_str = not in_str
                cur += ch
            elif ch == ',' and not in_str:
                args.append(cur.strip())
                cur = ""
            else:
                cur += ch
        if cur.strip():
            args.append(cur.strip())
        return args
    
    def _exec_if(self, rest: str, inst=None):
        """IF cond {body} (MSM: B-tree opcode 'i')."""
        # Simple: I cond S x=1 (sin bloques)
        parts = rest.split(None, 1)
        if parts:
            cond = parts[0]
            body = parts[1] if len(parts) > 1 else ""
            result = self._eval_expr(cond)
            if result:
                if body:
                    # Ejecutar cuerpo como sub-script
                    vm2 = StackVM()
                    vm2.vars = self.vars
                    vm2.compile(body).exec()
                    self.vars = vm2.vars
    
    def _exec_for(self, rest, inst=None):
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
            # Resolver variable en ref: ^ns(var) → ^ns("valor")
            resolved = ref
            if var and var in resolved:
                resolved = resolved.replace('(' + var + ')', '("' + key + '")')
            result = eval_function('$O', resolved)
            if not result: break
            self.vars[var] = result; self.ops.append(result)
            key = result
            if 'Q:' in rest:
                cond = rest.split('Q:',1)[1].strip()
                if self._eval_expr(cond): break


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

    def _exec_kill(self, rest: str, inst=None):
        """KILL var (MSM: B-tree opcode 'k')."""
        name = rest.strip()
        if name in self.vars:
            del self.vars[name]
    
    def _exec_quit(self, rest: str, inst=None):
        """QUIT[:cond] — salir de subrutina o script.
        
        Si hay call_stack: retorna a la subrutina llamante.
        Si no: termina el script.
        """
        if rest:
            cond = self._eval_expr(rest)
            if not cond:
                return
        
        if self.call_stack:
            # Retornar de subrutina
            self.ip = self.call_stack.pop()
        else:
            # Terminar script
            self.quit_flag = True
    
    def _exec_get(self, rest: str, inst=None):
        """$GET(^ns(subs)) — llama a PDB tools."""
        result = self._call_func("$G", rest)
        self.ops.append(result)
        return result
    
    def _exec_data(self, rest: str, inst=None):
        """$DATA(^ns(subs)) — llama a PDB tools."""
        result = self._call_func("$D", rest)
        self.ops.append(result)
        return result
    
    def _exec_order(self, rest: str, inst=None):
        """$ORDER(^ns(subs)) — llama a PDB tools."""
        result = self._call_func("$O", rest)
        self.ops.append(result)
        return result
    
    def _call_func(self, name: str, raw_args: str) -> Any:
        """Llamar a $function desde la function table."""
        try:
            from m_funcs import eval_function
            return eval_function(name, raw_args, self)
        except ImportError:
            return f"[{name} not available]"
    
    def _exec_indir(self, rest: str, inst=None):
        """^ (INDIRECT) — referencia dinámica (MSM: opcode '^')."""
        self.ops.append(f"^{rest}")
    
    def _exec_nop(self, rest: str, inst=None):
        """NOP — expresión suelta."""
        if rest:
            result = self._eval_expr(rest)
            if result is not None:
                self.ops.append(result)
    
    def _eval_expr(self, expr: str) -> Any:
        expr = expr.strip()
        if not expr: return None
        
        # Variable local (MUMPS: undefined = 0 en aritmética)
        if expr in self.vars:
            v = self.vars[expr]
            if v is None: return 0
            return v
        
        # Número
        try:
            if '.' in expr: return float(expr)
            return int(expr)
        except: pass
        
        # String
        if expr.startswith('"') and expr.endswith('"'):
            return expr[1:-1]
        
        # Operación aritmética simple
        for op in ('+', '-', '*', '/'):
            if op in expr:
                parts = expr.split(op, 1)
                left = self._eval_expr(parts[0].strip())
                right = self._eval_expr(parts[1].strip())
                if left is None: left = 0
                if right is None: right = 0
                if op == '+': return left + right
                elif op == '-': return left - right
                elif op == '*': return left * right
                elif op == '/': return left / right if right != 0 else 0
        
        # Comparación
        for op in ('>=', '<=', '!=', '>', '<', '='):
            if op in expr:
                parts = expr.split(op, 1)
                left = self._eval_expr(parts[0].strip())
                right = self._eval_expr(parts[1].strip())
                if left is None: left = 0
                if right is None: right = 0
                if op == '=': return left == right
                elif op == '>': return left > right
                elif op == '<': return left < right
                elif op == '>=': return left >= right
                elif op == '<=': return left <= right
                elif op == '!=': return left != right
        
        return None
    
    def reset(self):
        """Reset VM (MSM: new context)."""
        self.ops = []
        self.instrs = []
        self.ip = 0
        self.vars = {}
        self.quit_flag = False
        self.error = None


# ── CLI ──

if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "S x=42 W x"
    
    vm = StackVM()
    print(f"📋 Compiling: {code}")
    vm.compile(code)
    print(f"   Instructions: {len(vm.instrs)}")
    for i, inst in enumerate(vm.instrs):
        print(f"   [{i}] {inst}")
    
    print(f"\n⚡ Executing...")
    result = vm.exec()
    print(f"\nResult: {result}")
