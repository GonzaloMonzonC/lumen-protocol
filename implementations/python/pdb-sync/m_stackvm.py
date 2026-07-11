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
    ("G",    OP_GET),
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
        """Compilar código M a lista de StackOp."""
        self.instrs = []
        for line in code.split('\n'):
            line = line.strip()
            if not line or line.startswith(';'):
                continue
            # Comando simple
            token = line.split()[0] if line.split() else ""
            # : (...) → token="$G"
            if token.startswith("$") and "(" in token:
                func_name = token.split("(")[0]
                rest = line[len(func_name):].strip()
                op = op_dispatch(func_name)
            else:
                op = op_dispatch(token)
                if op:
                    rest = line[len(token):].strip()
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
        """WRITE expr (MSM: B-tree opcode 'w')."""
        if rest:
            result = self._eval_expr(rest)
            self.ops.append(result)
            if hasattr(self, '_on_write') and self._on_write:
                self._on_write(str(result))
    
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
    
    def _exec_for(self, rest: str, inst=None):
        """FOR var=start:step:limit {body} (MSM: B-tree opcode 'f')."""
        # Formato: var=start:step:limit {body}
        if '=' in rest:
            var, _, rest2 = rest.partition('=')
            var = var.strip()
            # Parsear range
            range_part = rest2.split(None, 1)[0] if rest2.split() else ""
            body = rest2[len(range_part):].strip() if len(rest2) > len(range_part) else ""
            
            parts = range_part.split(':')
            start = self._eval_expr(parts[0]) if parts[0] else 1
            step = self._eval_expr(parts[1]) if len(parts) > 1 and parts[1] else 1
            limit = self._eval_expr(parts[2]) if len(parts) > 2 and parts[2] else None
            
            i = int(start)
            while limit is None or i <= int(limit):
                self.vars[var] = i
                if body:
                    vm2 = StackVM()
                    vm2.vars = self.vars
                    vm2.compile(body).exec()
                    self.vars = vm2.vars
                i += int(step)
    
    def _exec_kill(self, rest: str, inst=None):
        """KILL var (MSM: B-tree opcode 'k')."""
        name = rest.strip()
        if name in self.vars:
            del self.vars[name]
    
    def _exec_quit(self, rest: str, inst=None):
        """QUIT[:cond] (MSM: B-tree opcode 'q')."""
        if not rest:
            self.quit_flag = True
        else:
            cond = self._eval_expr(rest)
            if cond:
                self.quit_flag = True
    
    def _exec_get(self, rest: str, inst=None):
        """$GET(^ns(subs)) (MSM: B-tree opcode 'g')."""
        self.ops.append(f"$GET({rest})")
    
    def _exec_data(self, rest: str, inst=None):
        """$DATA(^ns(subs)) (MSM: B-tree opcode 'q')."""
        self.ops.append(f"$DATA({rest})")
    
    def _exec_order(self, rest: str, inst=None):
        """$ORDER(^ns(subs)) (MSM: B-tree opcode 'o')."""
        self.ops.append(f"$ORDER({rest})")
    
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
        """Evaluar expresión simple.
        
        TODO v2: stack-based con precedencia de operadores.
        Ahora: evalúa literales, variables, y operaciones básicas.
        """
        expr = expr.strip()
        if not expr:
            return None
        
        # Variable local
        if expr in self.vars:
            return self.vars[expr]
        
        # Número
        try:
            if '.' in expr:
                return float(expr)
            return int(expr)
        except:
            pass
        
        # String
        if expr.startswith('"') and expr.endswith('"'):
            return expr[1:-1]
        
        # Operación aritmética simple
        for op in ('+', '-', '*', '/'):
            if op in expr:
                parts = expr.split(op, 1)
                left = self._eval_expr(parts[0].strip())
                right = self._eval_expr(parts[1].strip())
                if left is not None and right is not None:
                    if op == '+': return left + right
                    elif op == '-': return left - right
                    elif op == '*': return left * right
                    elif op == '/': return left / right
        
        # Comparación
        for op in ('>=', '<=', '!=', '>', '<', '='):
            if op in expr:
                parts = expr.split(op, 1)
                left = self._eval_expr(parts[0].strip())
                right = self._eval_expr(parts[1].strip())
                if left is not None and right is not None:
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
