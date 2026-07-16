# ── VM Version ──
VM_VERSION = "2.1.0"

#!/usr/bin/env python3
"""
m_stackvm.py — Stack-based expression evaluator para M-Light v2.

Inspirado en MSM FUN_00440ca0 (bytecode executor, 1.538 instr).

Arquitectura (Zalo):
  - Pila de operandos + operadores
  - Error trap nativo ($ECODE/$ZERROR)
  - B-tree ligero para dispatch de opcodes
  - Opcodes prioritarios: SET, WRITE, IF, FOR, ELSE, NEW
  - FOR + INDIRECT integrados desde diseño

v2.1:
  - Múltiples comandos por línea (W "a" Q) — tokenizador consciente de
    comillas y paréntesis, como el line scanner de MSM.
  - Postcondicionales (Q:cond, W:cond, ...).
  - ELSE con $TEST.
  - FOR sin argumentos (F  S k=$O(...) Q:k=""  body) con presupuesto de
    tiempo — no puede colgarse: corta por _timeout.
  - Evaluador: concatenación _, comparaciones M, aridad izquierda→derecha,
    resolución de variables en argumentos de $funciones y subíndices de
    ^GLOBALs.
  - WRITE output via hook _on_write (se propaga a sub-VMs de FOR/IF/ELSE).
  - Bloques con punto (dot-blocks) NO soportados: esas líneas se ignoran.

Autor: Hermes + CadencesLab
Licencia: MIT
"""

import sys, os, re, time
from typing import Any, Optional

# ── Error trap nativo (MSM: FUN_0043eac0 pattern) ──

class MError(Exception):
    """Error MUMPS con $ECODE/$ZERROR (MSM: FUN_0043eac0 style)."""
    def __init__(self, code: int, msg: str, context: dict = None):
        self.ecode = f"M{code}"        # $ECODE: código de error
        self.zerror = msg               # $ZERROR: mensaje
        self.context = context or {}
        super().__init__(f"[{self.ecode}] {self.zerror}")

# ── Opcodes ──

OP_PUSH   = "PUSH"    # Push valor a la pila
OP_POP    = "POP"     # Pop de la pila
OP_SET    = "SET"     # SET var = expr
OP_WRITE  = "WRITE"   # WRITE expr
OP_IF     = "IF"      # IF cond {resto de línea}
OP_ELSE   = "ELSE"    # ELSE {resto de línea} — ejecuta si '$TEST es falso
OP_FOR    = "FOR"     # FOR var=start:step:limit {body} | FOR  {body}
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
OP_TABLE = [  # sorted ASCII
    ("$D",   OP_DATA),
    ("$G",   OP_GET),
    ("$O",   OP_ORDER),
    ("D",    OP_DO),
    ("E",    OP_ELSE),
    ("F",    OP_FOR),
    ("G",    OP_GOTO),  # G = GOTO (no GET, eso es \$G)
    ("I",    OP_IF),
    ("K",    OP_KILL),
    ("N",    OP_NEW),
    ("Q",    OP_QUIT),
    ("S",    OP_SET),
    ("W",    OP_WRITE),
    ("^",    OP_INDIR),
]

# Nombres largos → abreviatura canónica
CMD_MAP = {
    "SET": "S", "WRITE": "W", "IF": "I", "FOR": "F", "QUIT": "Q",
    "DO": "D", "GOTO": "G", "KILL": "K", "NEW": "N", "ELSE": "E",
}

# Tokens que son comandos M (para distinguir labels de comandos)
CMD_TOKENS = {"S", "SET", "K", "KILL", "F", "FOR", "I", "IF", "W", "WRITE",
              "Q", "QUIT", "D", "DO", "G", "GOTO", "R", "READ", "N", "NEW",
              "O", "OPEN", "C", "CLOSE", "U", "USE", "E", "ELSE", "H", "HALT"}


def op_dispatch(token: str) -> Optional[str]:
    """B-tree ligero: binary search sobre OP_TABLE."""
    t = token  # No upper() — ^ no es letra
    if t.isalpha():
        t = t.upper()
        t = CMD_MAP.get(t, t)
    lo, hi = 0, len(OP_TABLE) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        name, op = OP_TABLE[mid]
        if t == name: return op
        elif t < name: hi = mid - 1
        else: lo = mid + 1
    return None

# ── Tokenización consciente de comillas/paréntesis ──

def _scan_token(s: str, i: int) -> tuple:
    """Lee un token desde i. Un token termina en espacio a nivel superior;
    espacios dentro de "..." o (...) no cortan. → (token, índice_siguiente)."""
    n = len(s)
    while i < n and s[i] == ' ':
        i += 1
    start = i
    depth = 0
    in_str = False
    while i < n:
        ch = s[i]
        if ch == '"':
            in_str = not in_str
        elif not in_str:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth = max(0, depth - 1)
            elif ch == ' ' and depth == 0:
                break
        i += 1
    return s[start:i], i


def _split_top(s: str, sep: str) -> list:
    """Split por sep a nivel superior (fuera de comillas y paréntesis)."""
    parts = []
    cur = ""
    depth = 0
    in_str = False
    for ch in s:
        if ch == '"':
            in_str = not in_str
            cur += ch
        elif not in_str and ch == '(':
            depth += 1
            cur += ch
        elif not in_str and ch == ')':
            depth = max(0, depth - 1)
            cur += ch
        elif not in_str and depth == 0 and ch == sep:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def _scan_string(s: str, i: int) -> tuple:
    """Lee un literal M "..." desde i (comillas dobladas "" = comilla literal).
    → (contenido, índice tras la comilla de cierre)."""
    assert s[i] == '"'
    i += 1
    out = ""
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == '"':
            if i + 1 < n and s[i + 1] == '"':
                out += '"'
                i += 2
                continue
            return out, i + 1
        out += ch
        i += 1
    return out, i  # sin cierre: tolerante


_NUM_PREFIX = re.compile(r'^[+-]?(\d+\.?\d*|\.\d+)')

def _mnum(v) -> Any:
    """Conversión numérica canónica M: prefijo numérico o 0."""
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return v
    if v is None:
        return 0
    m = _NUM_PREFIX.match(str(v).strip())
    if not m:
        return 0
    t = m.group(0)
    try:
        return int(t)
    except ValueError:
        return float(t)


def _is_numeric(v) -> bool:
    if isinstance(v, bool):
        return True
    if isinstance(v, (int, float)):
        return True
    s = str(v).strip()
    m = _NUM_PREFIX.match(s)
    return bool(m) and m.group(0) == s


_OPS2 = ('>=', '<=', '!=', "'=")
_OPS1 = ('_', '+', '-', '*', '/', '>', '<', '=', '&')

def _top_level_ops(expr: str) -> list:
    """Posiciones de operadores binarios a nivel superior. → [(pos, op)]"""
    found = []
    depth = 0
    in_str = False
    i = 0
    n = len(expr)
    prev = ''  # último char significativo anterior
    while i < n:
        ch = expr[i]
        if ch == '"':
            in_str = not in_str
            prev = ch
            i += 1
            continue
        if in_str:
            i += 1
            continue
        if ch == '(':
            depth += 1
            prev = ch
            i += 1
            continue
        if ch == ')':
            depth = max(0, depth - 1)
            prev = ch
            i += 1
            continue
        if depth == 0:
            two = expr[i:i + 2]
            if two in _OPS2:
                if prev not in ('', '(', '+', '-', '*', '/', '>', '<', '=', '_', '&', "'"):
                    found.append((i, two))
                prev = two[-1]
                i += 2
                continue
            if ch in _OPS1:
                # unario (+/-) al inicio o tras otro operador: no es split point
                if prev in ('', '(', '+', '-', '*', '/', '>', '<', '=', '_', '&', "'"):
                    prev = ch
                    i += 1
                    continue
                found.append((i, ch))
                prev = ch
                i += 1
                continue
        if ch != ' ':
            prev = ch
        i += 1
    return found

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
    """Stack-based VM para MUMPS (MSM FUN_00440ca0 pattern)."""

    def __init__(self):
        self.ops = []           # pila de operandos
        self.instrs = []        # lista de instrucciones
        self.labels = {}        # label → índice de instrucción
        self.call_stack = []    # retornos de DO label
        self.ip = 0             # instruction pointer
        self.vars = {}          # variables locales
        self.quit_flag = False
        self.error = None       # último $ECODE
        self._on_write = None   # hook: callable(str) por cada WRITE
        self._start_time = 0
        self._timeout = 10      # max segundos por ejecución

    # ── Compilación (MCompiler simplificado) ──

    def compile(self, code: str):
        self.instrs = []
        self.labels = {}
        self.call_stack = []
        for line in code.split('\n'):
            stripped = line.strip()
            if not stripped or stripped.startswith(';'):
                continue
            if stripped.startswith('.'):
                # dot-block (no soportado por este VM): se ignora
                continue
            text = stripped
            if line[0] not in ' \t':
                # Posible label a columna 0 (regla de columnas de MUMPS)
                first, after = _scan_token(text, 0)
                base = first.split('(')[0]
                if base.isidentifier() and base == base.upper():
                    rest = text[after:].strip()
                    nxt, _ = _scan_token(rest, 0) if rest else ("", 0)
                    nxt_base = nxt.partition(':')[0]
                    nxt_is_cmd = (nxt_base.isalpha() and nxt_base.upper() in CMD_TOKENS) \
                                 or nxt.startswith('$') or nxt.startswith('^')
                    if base not in CMD_TOKENS:
                        self.labels[base] = len(self.instrs)
                        text = rest
                    elif rest and nxt_is_cmd and base not in ("F", "FOR", "E", "ELSE"):
                        # comando conocido usado como nombre de label
                        # (F/E se excluyen: "F S ..." es FOR sin argumentos y
                        # "E  W ..." es ELSE, no labels)
                        self.labels[base] = len(self.instrs)
                        text = rest
            if text and not text.startswith(';'):
                self._compile_commands(text, line)
        return self

    def _compile_commands(self, text: str, source: str):
        """Compila una secuencia de comandos M de una línea."""
        i = 0
        n = len(text)
        while i < n:
            tok, j = _scan_token(text, i)
            if not tok or tok.startswith(';'):
                break
            # $func a nivel de comando: $G(...), $O(...), $D(...)
            if tok.startswith('$'):
                name = tok.split('(')[0]
                op = op_dispatch(name)
                if op:
                    self.instrs.append(StackOp(op, {"rest": tok[len(name):]}, source))
                else:
                    self.instrs.append(StackOp(OP_NOP, {"expr": tok}, source))
                i = j
                continue
            if tok.startswith('^'):
                self.instrs.append(StackOp(OP_INDIR, {"rest": tok[1:]}, source))
                i = j
                continue
            head, _, postcond = tok.partition(':')
            op = op_dispatch(head) if head else None
            if op is None:
                self.instrs.append(StackOp(OP_NOP, {"expr": tok}, source))
                i = j
                continue
            if op in (OP_FOR, OP_IF, OP_ELSE):
                # Su ámbito es el resto de la línea
                scope = text[j:].strip()
                # M de una línea estilo test: un Q suelto al final pertenece a
                # la rutina, no al ámbito del FOR/IF (Q dentro cortaría el loop)
                lifted_quit = False
                if scope == 'Q' or scope.endswith(' Q'):
                    scope = scope[:-1].rstrip()
                    lifted_quit = True
                self.instrs.append(StackOp(op, {"rest": scope, "post": postcond}, source))
                if lifted_quit:
                    self.instrs.append(StackOp(OP_QUIT, {"rest": ""}, source))
                break
            if op == OP_QUIT:
                # Q[:cond] — la condición viaja en el propio token
                self.instrs.append(StackOp(op, {"rest": postcond}, source))
                i = j
                continue
            # Comando con (posible) argumento: el siguiente token
            arg, k = _scan_token(text, j)
            arg_base = arg.partition(':')[0]
            arg_is_cmd = (arg_base.isalpha() and arg_base.upper() in CMD_TOKENS
                          and op in (OP_HALT,))
            if arg_is_cmd:
                arg, k = "", j
            self.instrs.append(StackOp(op, {"rest": arg, "post": postcond}, source))
            i = k

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
        if not self._start_time:
            self._start_time = time.time()

        try:
            while 0 <= self.ip < len(self.instrs) and not self.quit_flag:
                self._check_timeout()
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

    def _check_timeout(self):
        """Timeout (MSM: $ZTIME limit)."""
        if self._start_time and time.time() - self._start_time > self._timeout:
            raise MError(9, "TIMEOUT", {"ip": self.ip})

    def _exec_op(self, inst: StackOp):
        """Ejecutar una instrucción (MSM: opcode dispatch)."""
        post = inst.args.get("post")
        if post and not self._eval_expr(post):
            return  # postcondicional falsa: comando saltado
        h = {
            OP_SET:   self._exec_set,
            OP_WRITE: self._exec_write,
            OP_IF:    self._exec_if,
            OP_ELSE:  self._exec_else,
            OP_FOR:   self._exec_for,
            OP_KILL:  self._exec_kill,
            OP_QUIT:  self._exec_quit,
            OP_DO:    self._exec_do,
            OP_GOTO:  self._exec_goto,
            OP_GET:   self._exec_get,
            OP_DATA:  self._exec_data,
            OP_ORDER: self._exec_order,
            OP_INDIR: self._exec_indir,
            OP_NEW:   self._exec_new,
            OP_NOP:   self._exec_nop,
        }
        handler = h.get(inst.opcode)
        if handler:
            handler(inst.args.get("rest", ""), inst)
        else:
            self.ops.append((inst.opcode, inst.args))

    def _run_sub(self, code: str) -> bool:
        """Ejecutar un sub-script (cuerpo de FOR/IF/ELSE) compartiendo vars y
        hook de WRITE. → True si el sub-script hizo QUIT."""
        vm2 = StackVM()
        vm2.vars = self.vars           # mismo dict: mutaciones compartidas
        vm2._on_write = self._on_write
        vm2._timeout = self._timeout
        vm2._start_time = self._start_time
        vm2.compile(code)
        r = vm2.exec()
        if isinstance(r, dict) and r.get("error"):
            raise MError(98, f"{r['error']}: {r.get('msg', '')}")
        return vm2.quit_flag

    # ── Handlers ──

    def _exec_set(self, rest: str, inst=None):
        """SET var=expr[,var2=expr2] (MSM: B-tree opcode 's')."""
        for assign in _split_top(rest, ','):
            assign = assign.strip()
            if not assign or '=' not in assign:
                continue
            name, _, val = assign.partition('=')
            name = name.strip()
            try:
                result = self._eval_expr(val.strip())
            except MError:
                raise
            except Exception as e:
                raise MError(3, f"SET error: {e}", {"var": name, "val": val})
            if name.startswith('^'):
                self._set_global(name, result)
            else:
                self.vars[name] = result
            self.ops.append(result)

    def _set_global(self, ref: str, value):
        """SET ^NS(subs)=value — escribe en PDB con subíndices resueltos."""
        resolved = self._resolve_gref(ref)
        ns, subs = self._parse_gref(resolved)
        try:
            sp = _paths_dir()
            if sp and sp not in sys.path:
                sys.path.insert(0, sp)
            from pdb_tools import tool_set
            tool_set({"ns": ns, "subs": subs, "value": "" if value is None else str(value)})
        except ImportError:
            pass  # PDB no disponible: SET global es no-op

    @staticmethod
    def _parse_gref(ref: str) -> tuple:
        """'^NS("a","b")' → ("NS", ["a", "b"])."""
        if '(' not in ref:
            return ref.lstrip('^'), []
        ns = ref[1:ref.index('(')]
        inner = ref[ref.index('(') + 1:ref.rindex(')')]
        subs = [s.strip().strip('"') for s in _split_top(inner, ',')]
        return ns, subs

    def _parse_write_args(self, s: str) -> list:
        """Argumentos de WRITE separados por coma (quote/paren-aware)."""
        return [p.strip() for p in _split_top(s, ',')]

    def _exec_write(self, rest: str, inst=None):
        """WRITE expr[,expr...] — strings, !, concatenación, $funcs."""
        if not rest:
            return
        output = ""
        for part in self._parse_write_args(rest):
            if not part:
                continue
            if part == "!":
                output += "\n"
                continue
            if part == "#" or part.startswith("?"):
                continue  # form-feed / tabulación: no aplican
            if part.startswith('"'):
                lit, end = _scan_string(part, 0)
                if end == len(part):
                    output += lit
                    continue
            val = self._eval_expr(part)
            if val is not None:
                output += str(val)
        self.ops.append(output)
        if self._on_write:
            self._on_write(output)

    def _exec_if(self, rest: str, inst=None):
        """IF cond {resto de línea} — deja $TEST."""
        cond_tok, j = _scan_token(rest, 0)
        if not cond_tok:
            return
        body = rest[j:].strip()
        result = self._eval_expr(cond_tok)
        self.vars['$TEST'] = 1 if result else 0
        if result and body:
            if self._run_sub(body):
                self.quit_flag = True

    def _exec_else(self, rest: str, inst=None):
        """ELSE {resto de línea} — ejecuta si $TEST es falso."""
        if not self.vars.get('$TEST', 0):
            if rest and self._run_sub(rest):
                self.quit_flag = True

    def _exec_for(self, rest, inst=None):
        """FOR var=start:step:limit {body} | FOR {body} (sin argumentos).

        La forma sin argumentos itera hasta que el body haga QUIT (Q:cond).
        Ambas formas respetan el presupuesto de tiempo del VM (no cuelgan).
        """
        rest = rest.strip()
        if not rest:
            return
        tok0, j = _scan_token(rest, 0)
        rng = tok0.partition('=')[2] if '=' in tok0 else ""
        if rng and not tok0.startswith('$') and ':' in rng:
            # FOR numérico: var=start:step:limit
            var = tok0.partition('=')[0].strip()
            parts = _split_top(rng, ':')
            start = self._eval_expr(parts[0]) if parts[0] else 1
            step = self._eval_expr(parts[1]) if len(parts) > 1 and parts[1] else 1
            limit = self._eval_expr(parts[2]) if len(parts) > 2 and parts[2] else None
            body = rest[j:].strip()
            i = _mnum(start)
            step_n = _mnum(step) or 1
            while True:
                self._check_timeout()
                if limit is not None:
                    lim_n = _mnum(limit)
                    if (step_n > 0 and i > lim_n) or (step_n < 0 and i < lim_n):
                        break
                self.vars[var] = i
                if body and self._run_sub(body):
                    break
                if limit is None and not body:
                    break  # F var=x sin límite ni body: una pasada
                i += step_n
        else:
            # FOR sin argumentos. Forma canónica de scan:
            #   F  S var=$O(ref) [Q:cond] [body]
            # Semántica legado (tests_imp05): la var conserva la ÚLTIMA
            # clave no vacía y cada clave se apila en self.ops.
            scan = self._parse_order_scan(rest)
            if scan:
                var, expr, qcond, body = scan
                while True:
                    self._check_timeout()
                    val = self._eval_expr(expr)
                    if val is None or val == "":
                        break
                    self.vars[var] = val
                    self.ops.append(val)
                    if qcond and self._eval_expr(qcond):
                        break
                    if body and self._run_sub(body):
                        break
            else:
                # Genérico: el body corta con QUIT (p.ej. Q:k>3)
                while True:
                    self._check_timeout()
                    if self._run_sub(rest):
                        break

    @staticmethod
    def _parse_order_scan(rest: str):
        """Detecta 'S var=$O(ref) [Q:cond] [body]'. → (var, expr, cond, body) | None."""
        t0, i = _scan_token(rest, 0)
        if t0.upper() not in ("S", "SET"):
            return None
        t1, j = _scan_token(rest, i)
        var, _, expr = t1.partition('=')
        if not expr.startswith('$O('):
            return None
        t2, k = _scan_token(rest, j)
        qcond = ""
        body_start = j
        if t2.startswith('Q:'):
            qcond = t2[2:]
            body_start = k
        return var.strip(), expr, qcond, rest[body_start:].strip()

    def _exec_do(self, rest, inst=None):
        '''DO label — llamar a subrutina con labels.'''
        rest = rest.strip()
        if not rest:
            return  # DO sin argumento (dot-block): no soportado
        label = rest.split('(')[0].upper() if '(' in rest else rest.upper()
        if label in self.labels:
            self.call_stack.append(self.ip)
            self.ip = self.labels[label]
        elif rest.startswith('^'):
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
        """KILL var[,var2] | KILL ^ns(subs)."""
        for name in _split_top(rest, ','):
            name = name.strip()
            if not name:
                continue
            if name.startswith('^'):
                resolved = self._resolve_gref(name)
                ns, subs = self._parse_gref(resolved)
                try:
                    from pdb_tools import tool_kill
                    tool_kill({"ns": ns, "subs": subs})
                except ImportError:
                    pass
            else:
                self.vars.pop(name, None)

    def _exec_new(self, rest: str, inst=None):
        """NEW var[,var2] — variables frescas (sin pila de scopes: kill)."""
        for name in rest.split(','):
            name = name.strip()
            if name:
                self.vars.pop(name, None)

    def _exec_quit(self, rest: str, inst=None):
        """QUIT[:cond] — salir de subrutina o script."""
        if rest:
            cond = self._eval_expr(rest)
            if not cond:
                return
        if self.call_stack:
            self.ip = self.call_stack.pop()
        else:
            self.quit_flag = True

    def _exec_get(self, rest: str, inst=None):
        """$GET(^ns(subs)) — llama a PDB tools."""
        result = self._eval_expr(f"$G{rest}")
        self.ops.append(result)
        return result

    def _exec_data(self, rest: str, inst=None):
        """$DATA(^ns(subs)) — llama a PDB tools."""
        result = self._eval_expr(f"$D{rest}")
        self.ops.append(result)
        return result

    def _exec_order(self, rest: str, inst=None):
        """$ORDER(^ns(subs)) — llama a PDB tools."""
        result = self._eval_expr(f"$O{rest}")
        self.ops.append(result)
        return result

    def _exec_indir(self, rest: str, inst=None):
        """^ (INDIRECT) — referencia dinámica (MSM: opcode '^')."""
        self.ops.append(f"^{rest}")

    def _exec_nop(self, rest: str, inst=None):
        """NOP — expresión suelta."""
        expr = (inst.args.get("expr", "") if inst else "") or rest
        if expr:
            try:
                result = self._eval_expr(expr)
            except MError:
                return
            if result is not None:
                self.ops.append(result)

    # ── Evaluador de expresiones ──

    def _eval_expr(self, expr: str) -> Any:
        if not isinstance(expr, str):
            return expr
        expr = expr.strip()
        if not expr:
            return None

        # Variable local ($1, $TEST, x, html, ...)
        if expr in self.vars:
            v = self.vars[expr]
            return 0 if v is None else v

        # Literal string completo
        if expr.startswith('"'):
            lit, end = _scan_string(expr, 0)
            if end == len(expr):
                return lit

        # Número
        try:
            return int(expr)
        except ValueError:
            pass
        try:
            return float(expr)
        except ValueError:
            pass

        # Operadores binarios a nivel superior (M: izquierda→derecha,
        # sin precedencia ⇒ dividir por el último operador)
        found = _top_level_ops(expr)
        if found:
            pos, op = found[-1]
            left = expr[:pos]
            right = expr[pos + len(op):]
            l = self._eval_expr(left)
            r = self._eval_expr(right)
            return self._apply_op(op, l, r)

        # $funcion(args)
        if expr.startswith('$') and '(' in expr and expr.endswith(')'):
            return self._eval_func(expr)

        # ^GLOBAL directo en expresión → lectura
        if expr.startswith('^'):
            try:
                from m_funcs import func_get
                return func_get([self._resolve_gref(expr)], self)
            except ImportError:
                return ""

        # $especial sin paréntesis ($ZARGS ya cae por vars)
        if expr.startswith('$'):
            return self.vars.get(expr, "")

        if expr.isidentifier():
            if expr == expr.lower():
                # legado: identificador en minúscula no definido → literal
                return expr
            raise MError(8, f"UNDEFINED {expr}", {"var": expr})

        return None

    def _apply_op(self, op: str, l, r):
        if op == '_':
            return f"{'' if l is None else l}{'' if r is None else r}"
        if op in ('+', '-', '*', '/'):
            ln, rn = _mnum(l), _mnum(r)
            if op == '+': res = ln + rn
            elif op == '-': res = ln - rn
            elif op == '*': res = ln * rn
            else: res = ln / rn if rn != 0 else 0
            if isinstance(res, float) and res.is_integer():
                res = int(res)
            return res
        if op in ('=', '!=', "'="):
            if _is_numeric(l) and _is_numeric(r):
                eq = _mnum(l) == _mnum(r)
            else:
                eq = str(l if l is not None else "") == str(r if r is not None else "")
            return (1 if eq else 0) if op == '=' else (0 if eq else 1)
        if op in ('>', '<', '>=', '<='):
            ln, rn = _mnum(l), _mnum(r)
            if op == '>': return 1 if ln > rn else 0
            if op == '<': return 1 if ln < rn else 0
            if op == '>=': return 1 if ln >= rn else 0
            return 1 if ln <= rn else 0
        if op == '&':
            return 1 if (l and r) else 0
        return None

    def _eval_func(self, expr: str):
        """$FUNC(args) con argumentos resueltos (vars, $funcs anidadas,
        subíndices de ^GLOBALs)."""
        name = expr.split('(')[0]
        raw = expr[len(name) + 1:-1]  # sin paréntesis externos
        args = _split_top(raw, ',')

        # $G(local[,default]) — la var puede no existir: no debe dar error
        if name in ('$G', '$GET') and args and args[0].strip() and not args[0].strip().startswith('^'):
            key = args[0].strip()
            default = self._eval_expr(args[1]) if len(args) > 1 else ""
            if key in self.vars:
                v = self.vars[key]
                return default if v is None else v
            if key.startswith('"'):
                lit, end = _scan_string(key, 0)
                if end == len(key):
                    return lit
            return default if default is not None else ""

        rebuilt = []
        for a in args:
            a = a.strip()
            if a == "":
                rebuilt.append('""')
                continue
            if a.startswith('^'):
                rebuilt.append(self._resolve_gref(a))
                continue
            if a.startswith('"'):
                lit, end = _scan_string(a, 0)
                if end == len(a):
                    rebuilt.append(a)
                    continue
            try:
                v = self._eval_expr(a)
            except MError:
                v = ""
            if isinstance(v, bool):
                rebuilt.append("1" if v else "0")
            elif isinstance(v, (int, float)):
                rebuilt.append(str(v))
            else:
                rebuilt.append('"' + str(v if v is not None else "").replace('"', '""') + '"')

        try:
            from m_funcs import eval_function
        except ImportError:
            return f"[{name} not available]"
        return eval_function(name, "(" + ",".join(rebuilt) + ")", self)

    def _resolve_gref(self, ref: str) -> str:
        """'^NS("a",var)' → '^NS("a","<valor>")' — resuelve subíndices."""
        if '(' not in ref:
            return ref
        ns = ref[:ref.index('(')]
        inner = ref[ref.index('(') + 1:ref.rindex(')')]
        out = []
        for s in _split_top(inner, ','):
            s = s.strip()
            if s == "":
                out.append('""')
            elif s.startswith('"'):
                out.append(s)
            elif s.isidentifier() and s not in self.vars:
                # var no definida en subíndice → "" (los scans $O parten de vacío)
                out.append('""')
            else:
                try:
                    v = self._eval_expr(s)
                except MError:
                    v = ""
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out.append(str(v))
                else:
                    out.append('"' + str(v if v is not None else "") + '"')
        return f"{ns}({','.join(out)})"

    def reset(self):
        """Reset VM (MSM: new context)."""
        self.ops = []
        self.instrs = []
        self.ip = 0
        self.vars = {}
        self.quit_flag = False
        self.error = None
        self._start_time = 0


def _paths_dir():
    """Directorio del stack PDB (para imports lazy de pdb_tools)."""
    try:
        import _paths
        return getattr(_paths, 'PDB_DIR_S', None)
    except ImportError:
        return None


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
