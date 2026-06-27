"""
M-Light — mini evaluador de expresiones y scripts M para PDB.

Soporta el subconjunto esencial de MUMPS que Gonzalo usaba:
  F  S N=$O(^nombres(N)) Q:N="pepe"
  F I=1:1:10 { S ^datos(I)=I*2 }
  S ^ns(subs)=value  Q:condition  S N=$O(^ns(N))

Operaciones: $GET, $DATA, $ORDER, $PIECE, $EXTRACT, $SELECT
Control: F (FOR infinito y con rango), Q:cond, S, K, IF/ELSE
"""

import re
from typing import Any, Optional


class MScope:
    """MUMPS-style scope with local variables and PDB reference."""
    def __init__(self, parent: 'MScope' = None):
        self.vars = {}        # local variables
        self.parent = parent  # parent scope for nested loops

    def get(self, name: str) -> Any:
        if name in self.vars:
            return self.vars[name]
        if self.parent:
            return self.parent.get(name)
        return None

    def set(self, name: str, value: Any):
        self.vars[name] = value


class MEvaluator:
    """Evalúa scripts M completos contra PDB real."""

    def __init__(self, pdb_tools_module=None):
        self.pdb = pdb_tools_module
        self.scope = MScope()
        self._quit_flag = False
        self._labels = {}
        self._label_mode = False
        self._goto_target = None
        self._call_stack = []
        self._do_call = False  # True when next jump is a DO, not GOTO

    # ── API pública ──

    def eval(self, code: str) -> Any:
        """Evaluar una línea o bloque de código M."""
        self._quit_flag = False
        return self._exec_line(code.strip())

    def eval_script(self, script: str) -> Any:
        """Ejecutar un script M multilínea con soporte de labels (GOTO/DO).
        Escanea labels primero, luego ejecuta línea por línea."""
        self._quit_flag = False
        self._labels = {}
        lines = script.strip().split('\n')

        # First pass: scan labels
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            # Label: LABEL ; code  o  LABEL code
            label_match = re.match(r'^(\w+)\s*[ ;]', line)
            if label_match:
                label = label_match.group(1)
                if label.upper() not in ('S', 'K', 'F', 'Q', 'I', 'W', 'D', 'G', 'N', 'O', 'U', 'C', 'V', 'Z', 'J', 'R'):
                    self._labels[label] = i  # line index

        # Second pass: execute with jump support (GOTO/DO)
        self._call_stack = []
        self._label_mode = False
        i = 0
        while i < len(lines) and not self._quit_flag:
            line = lines[i].strip()
            if not line:
                i += 1
                continue
            # Skip label-only lines
            if line in self._labels:
                i += 1
                continue
            # Strip label prefix if present
            code_line = line
            label_match = re.match(r'^(\w+)\s*[ ;]', line)
            if label_match and label_match.group(1) in self._labels:
                code_line = line[label_match.end():].strip()
            if code_line:
                self._exec_line(code_line)
            # Handle jumps
            if self._goto_target is not None:
                target = self._goto_target
                self._goto_target = None
                if target in self._labels:
                    if self._do_call:
                        self._do_call = False
                        self._call_stack.append(i + 1)  # return to next line
                    i = self._labels[target]
                    continue
            # Handle DO return: when QUIT fires and call stack not empty
            if self._quit_flag and self._call_stack:
                self._quit_flag = False
                i = self._call_stack.pop()
                continue
            i += 1

    def eval_expr(self, expr: str) -> Any:
        """Evaluar una expresión M (sin efectos secundarios)."""
        return self._resolve(expr.strip())

    # ── Ejecutor de líneas ──

    def _exec_line(self, line: str) -> Any:
        """Ejecuta una línea M (puede contener múltiples comandos separados por espacio)."""
        if not line or self._quit_flag:
            return None

        # Eliminar comentarios
        if ';' in line:
            line = line.split(';')[0]

        # Separar comandos en la misma línea
        # En M, los comandos se separan por espacio
        # Pero hay que respetar strings y expresiones anidadas
        result = None
        pos = 0
        while pos < len(line) and not self._quit_flag:
            # Saltar espacios
            while pos < len(line) and line[pos] == ' ':
                pos += 1
            if pos >= len(line):
                break

            # Identificar el comando (con posible postconditional :cond)
            cmd_match = re.match(r'(F(?:OR)?|S(?:ET)?|K(?:ILL)?|Q(?:UIT)?|IF|ELSE|W(?:RITE)?|D(?:O)?|G(?:OTO)?|R(?:EAD)?|N(?:EW)?|O(?:PEN)?|U(?:SE)?|C(?:LOSE)?)((?:[:][^ ]+)?)(?:\s|$)', line[pos:])
            if cmd_match:
                cmd = cmd_match.group(1)[0]  # Primera letra del comando
                pos += cmd_match.end()
                if cmd in ('F',):
                    pos = self._exec_for(line, pos)
                elif cmd in ('S',):
                    pos = self._exec_set(line, pos)
                elif cmd in ('K',):
                    pos = self._exec_kill(line, pos)
                elif cmd in ('Q',):
                    pos = self._exec_quit(line, pos, cmd_match.group(2) or "")
                elif cmd in ('I',):
                    pos = self._exec_if(line, pos)
                elif cmd in ('W',):
                    pos = self._exec_write(line, pos)
                elif cmd in ('G',):
                    pos = self._exec_goto(line, pos)
                elif cmd in ('D',):
                    pos = self._exec_do(line, pos)
                elif cmd in ('R',):
                    pos = self._exec_read(line, pos)
                elif cmd in ('N',):
                    pos = self._exec_new(line, pos)
                elif cmd in ('O',):
                    pos = self._exec_open(line, pos)
                elif cmd in ('U',):
                    pos = self._exec_use(line, pos)
                elif cmd in ('C',):
                    pos = self._exec_close(line, pos)
                else:
                    pos += 1
            else:
                # Puede ser una expresión suelta o resto de la línea
                break

        return result

    # ── FOR loop ──

    def _exec_for(self, line: str, pos: int) -> int:
        """Ejecuta FOR. Soporta:
           F  {...}                    → infinito con Q:cond
           F I=1:1:10 {...}            → con rango
           F I=1:1:10 S ^x(I)=I Q:I=5 → inline sin llaves
        """
        # Saltar espacios después de F
        while pos < len(line) and line[pos] == ' ':
            pos += 1

        # Crear scope hijo para el loop
        child = MScope(self.scope)
        old_scope = self.scope
        self.scope = child

        # Determinar tipo de FOR
        # FOR con variable: 'VAR=start:step:end'
        range_match = re.match(r'(\w+)\s*=\s*([^:]+):([^:]+):([^\s{]+)\s*(.*)', line[pos:])
        if range_match:
            var_name = range_match.group(1)
            start = float(self._resolve(range_match.group(2).strip()))
            step = float(self._resolve(range_match.group(3).strip()))
            end = float(self._resolve(range_match.group(4).strip()))
            body = range_match.group(5).strip()
            pos += range_match.end()
            val = start
            while val <= end and not self._quit_flag:
                child.set(var_name, val)
                if body.startswith('{'):
                    # Bloque con llaves
                    block_end = self._find_block_end(body)
                    self._exec_line(body[1:block_end])
                    pos = pos + block_end + 1
                else:
                    self._exec_line(body)
                val += step

        else:
            # FOR infinito: F  S N=$O(...) Q:cond
            body = line[pos:].strip()
            _max_iter = 100000
            _iter = 0
            while not self._quit_flag and _iter < _max_iter:
                _iter += 1
                old_quit = self._quit_flag
                if body.startswith('{'):
                    block_end = self._find_block_end(body)
                    self.eval(body[1:block_end])
                else:
                    self.eval(body)
                if self._quit_flag or old_quit:
                    break

        self.scope = old_scope
        # Propagar variables del child scope al parent (MUMPS semantics)
        for k, v in child.vars.items():
            old_scope.set(k, v)
        return len(line)

    def _find_block_end(self, s: str) -> int:
        """Encuentra el cierre de un bloque { ... } respetando anidamiento."""
        depth = 0
        for i, ch in enumerate(s):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return i
        return len(s) - 1

    # ── SET ──

    def _exec_set(self, line: str, pos: int) -> int:
        """SET var=value o SET ^ns(subs)=value o SET A=1,B=2"""
        original_section = line[pos:]  # keep for offset calc
        rest = original_section.strip()
        consumed = len(original_section) - len(rest)  # leading whitespace

        # Procesar una o más asignaciones separadas por coma
        while True:
            rest = rest.lstrip()
            if not rest:
                break

            # @(expr)=value — indirección
            g_match = re.match(r'@\((.+)\)\s*=\s*(.+)', rest)
            if g_match:
                expr_inner = g_match.group(1)
                val_expr = g_match.group(2)
                indir_result = self._resolve(expr_inner)
                # Get the value as a resolvable token
                val_token = val_expr[:self._cmd_boundary(val_expr)].strip()
                val_raw = val_token  # pass raw, M-Light will resolve
                if isinstance(indir_result, str) and indir_result.startswith('^'):
                    result_code = "S " + indir_result + "=" + val_raw
                    self.eval(result_code)
                    consumed += len(g_match.group(0)) - (len(val_expr) - self._cmd_boundary(val_expr))
                    rest = rest[consumed:]
                    if rest.startswith(','):
                        rest = rest[1:]
                        consumed += 1
                        continue
                    break

            # ^ns(subs)=value
            g_match = re.match(r'\^(\w+)\(([^)]+)\)\s*=\s*(.+)', rest)
            if g_match and self.pdb:
                ns = g_match.group(1)
                subs = self._parse_subs(g_match.group(2))
                value_expr = g_match.group(3)
                value_end = self._cmd_boundary(value_expr)
                value = self._resolve(value_expr[:value_end].strip())
                self.pdb.tool_set({"ns": ns, "subs": subs, "value": value})
                chunk = len(g_match.group(0)) - (len(value_expr) - value_end)
                consumed += chunk
                rest = rest[chunk:]
                if rest.startswith(','):
                    rest = rest[1:]
                    consumed += 1
                    continue
                break

            # var=value
            v_match = re.match(r'(\w+)\s*=\s*(.+)', rest)
            if v_match:
                var = v_match.group(1)
                value_expr = v_match.group(2)
                value_end = self._cmd_boundary(value_expr)
                value = self._resolve(value_expr[:value_end].strip())
                self.scope.set(var, value)
                chunk = len(v_match.group(0)) - (len(value_expr) - value_end)
                consumed += chunk
                rest = rest[chunk:]
                if rest.startswith(','):
                    rest = rest[1:]
                    consumed += 1
                    continue
                break

            break  # no match, exit

        return pos + consumed

        return pos + 1

    def _exec_goto(self, line: str, pos: int) -> int:
        """G label — GOTO. En _exec_line, establece _goto_target.
        En eval_script, el loop principal maneja el salto."""
        rest = line[pos:].strip()
        label = rest.split()[0] if rest else ""
        if label:
            self._goto_target = label
        return len(line)

    def _exec_do(self, line: str, pos: int) -> int:
        """D label — DO (call subroutine)."""
        rest = line[pos:].strip()
        m = re.match(r'\^?(\w+)', rest)
        if m:
            self._goto_target = m.group(1)
            self._do_call = True  # signals eval_script to push return point
        return len(line)

    def _cmd_boundary(self, s: str) -> int:
        """Encuentra dónde termina el valor (antes del siguiente comando M o coma)."""
        depth = 0
        for i, ch in enumerate(s):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif depth == 0 and (ch == ' ' or ch == ','):
                if ch == ',':
                    return i
                # ch == ' '
                if re.match(r'[FKSQIWDGRNUC]\b', s[i:].strip()):
                    return i
        return len(s)

    def _until_next_cmd(self, s: str) -> str:
        """Extrae el valor hasta el siguiente comando M."""
        depth = 0
        for i, ch in enumerate(s):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif ch == ' ' and depth == 0:
                rest = s[i:].strip()
                if re.match(r'[FKSQIWDGRNUC]\b', rest):
                    return s[:i].strip()
        return s.strip()

    # ── KILL ──

    def _exec_kill(self, line: str, pos: int) -> int:
        """KILL ^ns(subs) o KILL var — elimina global o variable local.
        Soporta KILL A,B,C (múltiples variables separadas por coma)."""
        rest = line[pos:].strip()
        # ^ns(subs)
        g_match = re.match(r'\^(\w+)\(([^)]+)\)', rest)
        if g_match and self.pdb:
            ns = g_match.group(1)
            subs = self._parse_subs(g_match.group(2))
            self.pdb.tool_kill({"ns": ns, "subs": subs})
            return len(line)
        # var (local variable) — puede ser A,B,C
        v_match = re.match(r'(\w+(?:,\w+)*)', rest)
        if v_match:
            vars_str = v_match.group(1)
            for var in vars_str.split(','):
                var = var.strip()
                if var:
                    self.scope.vars.pop(var, None)
            return pos + v_match.end()
        return len(line)

    # ── QUIT ──

    def _exec_quit(self, line: str, pos: int, postcond: str = "") -> int:
        """QUIT[:condition] — sale del bucle actual si se cumple la condición.
        postcond viene ya extraído por cmd_match. Si está vacío, QUIT sin condición."""
        if postcond and postcond.startswith(':'):
            cond = postcond[1:].strip()
            if self._eval_condition(cond):
                self._quit_flag = True
            return pos
        else:
            self._quit_flag = True
            return len(line)

    # ── IF ──

    def _exec_if(self, line: str, pos: int) -> int:
        """IF condition { ... } o IF condition command"""
        rest = line[pos:].strip()
        # IF condition { ... }
        if_match = re.match(r'([^{]+)\s*\{', rest)
        if if_match:
            cond = if_match.group(1).strip()
            brace_pos = if_match.end() - 1  # position of {
            block_end_rel = self._find_block_end(rest[brace_pos:])
            end_pos = min(brace_pos + block_end_rel, len(rest))
            body_text = rest[brace_pos+1 : end_pos]
            if self._eval_condition(cond):
                self._exec_line(body_text.strip())
            return len(line)

        # IF condition command (sin llaves)
        space_idx = rest.find('  ')
        if space_idx > 0:
            cond = rest[:space_idx].strip()
            cmd = rest[space_idx:].strip()
            if self._eval_condition(cond):
                self._exec_line(cmd)
        else:
            # Solo condición, evaluar
            self._eval_condition(rest)
        return len(line)

    # ── WRITE ──

    def _exec_write(self, line: str, pos: int) -> int:
        """WRITE — imprime expresiones separadas por coma.
        W *7 → bell, W ! → newline, W ?n → columna, W \"str\" → texto"""
        rest = line[pos:].strip()
        output = []
        for item in re.split(r',\s*', rest):
            if not item:
                continue
            item = item.strip()
            # Handle !! sequences (multiple newlines)
            if item.replace('!', '') == '':
                output.append('\n' * len(item))
            elif item.startswith('*'):
                try:
                    code = int(self._resolve(item[1:]))
                    output.append(chr(code))
                except:
                    output.append(f'[{item}]')
            elif item.startswith('?'):
                try:
                    col = int(self._resolve(item[1:]))
                    output.append(f'[COL{col}]')
                except:
                    output.append(f'[{item}]')
            else:
                val = self._resolve(item)
                output.append(str(val) if val is not None else '')
        print(f'[M-Light WRITE] {"".join(output)}')
        return len(line)

    def _exec_read(self, line: str, pos: int) -> int:
        """READ prompt:var — lee entrada (simulado)"""
        rest = line[pos:].strip()
        if ':' in rest:
            prompt, var = rest.split(':', 1)
            var = var.strip()
            if prompt:
                print(f'[M-Light READ prompt] {self._resolve(prompt.strip())}')
            # En modo demo, responder vacío
            self.scope.set(var, '')
        elif rest:
            self.scope.set(rest.strip(), '')
        return len(line)

    def _exec_new(self, line, pos):
        for v in line[pos:].strip().replace(',',' ').split():
            self.scope.vars.pop(v.strip(), None)
        return len(line)

    def _exec_open(self, line, pos):
        print(f'[M-Light OPEN] {line[pos:].strip()}')
        return len(line)

    def _exec_use(self, line, pos):
        print(f'[M-Light USE] {line[pos:].strip()}')
        return len(line)

    def _exec_close(self, line, pos):
        print(f'[M-Light CLOSE] {line[pos:].strip()}')
        return len(line)

    # ── Evaluación de expresiones ──

    def _resolve(self, token: str) -> Any:
        """Resuelve un token: expresión $, variable, literal."""
        token = token.strip()

        # $GET(^ns(subs)) — también $G
        m = re.match(r'\$(?:GET|G)\s*\(\^(\w+)\(([^)]+)\)\s*\)', token)
        if m and self.pdb:
            ns = m.group(1)
            subs = self._parse_subs(m.group(2))
            r = self.pdb.tool_get({"ns": ns, "subs": subs})
            return r.get("value")

        # $GET(var) — $G con variable local
        m = re.match(r'\$(?:GET|G)\s*\((\w+)\)', token)
        if m:
            var = self.scope.get(m.group(1))
            return var if var is not None else ""

        # $DATA(^ns(subs)) — también $D
        m = re.match(r'\$(?:DATA|D)\s*\(\^(\w+)\(([^)]+)\)\s*\)', token)
        if m and self.pdb:
            ns = m.group(1)
            subs = self._parse_subs(m.group(2))
            r = self.pdb.tool_data({"ns": ns, "subs": subs})
            return r.get("value", 0)

        # $ORDER(^ns(subs), dir) — el alma de M (también $O)
        m = re.match(r'\$(?:ORDER|O)\s*\(\^(\w+)\(([^)]+)\)\s*(?:,\s*([-]?\d+))?\s*\)', token)
        if m and self.pdb:
            ns = m.group(1)
            subs = self._parse_subs(m.group(2))
            direction = int(m.group(3)) if m.group(3) else 1
            r = self.pdb.tool_order({"ns": ns, "subs": subs, "direction": direction})
            # MUMPS $ORDER returns "" (empty string) when no more elements
            val = r.get("value")
            return val if val is not None else ""

        # $PIECE(string, delim, n) — también $P
        m = re.match(r'\$(?:PIECE|P)\s*\(\s*([^,]+)\s*,\s*["\']([^"\']+)["\']\s*,\s*(\d+)\s*\)', token)
        if m:
            string = self._resolve(m.group(1))
            delim = m.group(2)
            n = int(m.group(3))
            parts = str(string).split(delim)
            return parts[n-1] if n <= len(parts) else ""

        # $EXTRACT(string, from, to?) — también $E
        m = re.match(r'\$(?:EXTRACT|E)\s*\(\s*([^,]+)\s*,\s*(\d+)(?:\s*,\s*(\d+))?\s*\)', token)
        if m:
            string = str(self._resolve(m.group(1)))
            frm = int(m.group(2)) - 1
            to = int(m.group(3)) if m.group(3) else frm + 1
            return string[frm:to]

        # $SELECT(cond1:val1, ..., 1:default) — también $S
        m = re.match(r'\$(?:SELECT|S)\s*\(\s*(.+)\s*\)', token)
        if m:
            pairs = m.group(1).split(",")
            for pair in pairs:
                pair = pair.strip()
                if ":" in pair:
                    cond, val = pair.split(":", 1)
                    if self._eval_condition(cond.strip()):
                        return self._resolve(val.strip())
            return None

        # $LENGTH(string) — también $L
        m = re.match(r'\$(?:LENGTH|L)\s*\(\s*([^)]+)\s*\)', token)
        if m:
            val = str(self._resolve(m.group(1)))
            return len(val)

        # $FIND(string,substring) — también $F
        m = re.match(r'\$(?:FIND|F)\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)', token)
        if m:
            haystack = str(self._resolve(m.group(1)))
            needle = str(self._resolve(m.group(2)))
            pos = haystack.find(needle)
            return pos + len(needle) + 1 if pos >= 0 else 0

        # System variables: $J (job), $H (time), $IO (device)
        if token == '$J':
            return self.scope.get('$J') or '0'
        if token == '$H':
            import time
            return str(int(time.time()))
        if token == '$IO':
            return self.scope.get('$IO') or '0'
        if token == '$ZV':
            return 'LUMEN M-Light v1.0'
        if token == '$X':
            return 0
        if token == '$Y':
            return 0

        # $TRANSLATE(string,old,new) — también $TR
        m = re.match(r'\$(?:TRANSLATE|TR)\s*\(\s*([^,]+)\s*,\s*([^,]+)\s*,\s*([^)]+)\s*\)', token)
        if m:
            val = str(self._resolve(m.group(1)))
            old = str(self._resolve(m.group(2)))
            new = str(self._resolve(m.group(3)))
            table = str.maketrans(old, new)
            return val.translate(table)

        # #hex — hex literal (MUMPS: #FF = 255, #10 = 16)
        m = re.match(r'#([0-9A-Fa-f]+)$', token)
        if m:
            return int(m.group(1), 16)

        # +expr — unary plus / numeric cast
        m = re.match(r'^\+([^ ].*)$', token)
        if m:
            val = self._resolve(m.group(1))
            try: return float(val) if '.' in str(val) else int(float(val))
            except: return 0

        # ^ns(subs) — acceso directo a global (para @ indirección)
        m = re.match(r'\^(\w+)\(([^)]+)\)', token)
        if m and self.pdb:
            ns = m.group(1)
            subs = self._parse_subs(m.group(2))
            r = self.pdb.tool_get({"ns": ns, "subs": subs})
            return r.get("value")

        # @(expr) — indirección M (evalúa expr y usa el resultado como código)
        m = re.match(r'@\((.+)\)', token)
        if m:
            inner = self._resolve(m.group(1))
            if inner and isinstance(inner, str):
                return self._resolve(inner)
            return inner

        # _ concatenación de strings (M: "a"_"b" = "ab")
        if '_' in token and not token.startswith('$'):
            parts = [p.strip() for p in token.split('_')]
            if parts:
                try:
                    result = ''
                    for p in parts:
                        resolved = str(self._resolve(p))
                        result += resolved
                    return result
                except:
                    pass

        # Variable local
        if token in self.scope.vars or (self.scope.parent and token in self.scope.parent.vars):
            return self.scope.get(token)

        # Arithmetic expression — MUMPS evalúa left-to-right SIN precedencia
        # Soporta: \ div, # mod, ** exp, *, /, +, -
        # Ej: I\100000#10*2, +$G(x), 5*2+1
        if re.match(r'^[+\-]?\w[\w\\#\*\/+\-]*$', token) and any(op in token for op in ['\\','#','*','/','+','-']):
            # Left-to-right evaluation (MUMPS style)
            parts = re.split(r'(\\|#|\*\*|[\*\/+\-])', token)
            if len(parts) >= 3:
                result = self._resolve_num(parts[0].strip())
                i = 1
                while i < len(parts) - 1:
                    op = parts[i].strip()
                    right = self._resolve_num(parts[i+1].strip())
                    if op == '\\': result = int(result // right) if result is not None else 0
                    elif op == '#': result = int(result % right) if result is not None else 0
                    elif op == '**': result = (result ** right) if result is not None else 0
                    elif op == '*': result = (result * right) if result is not None else 0
                    elif op == '/': result = (result / right) if result is not None else 0
                    elif op == '+': result = (result + right) if result is not None else 0
                    elif op == '-': result = (result - right) if result is not None else 0
                    i += 2
                return int(result) if result == int(result) else result

        # Literal
        if token.startswith('"') and token.endswith('"'):
            return token[1:-1]
        try:
            return int(token)
        except ValueError:
            try:
                return float(token)
            except ValueError:
                return token

    def _resolve_num(self, token: str) -> float:
        """Resuelve un token a número (MUMPS: '1' → 1, #FF → 255, +$G(x) → numeric)."""
        token = token.strip()
        if not token:
            return 0
        if token.startswith('#'):
            try: return float(int(token[1:], 16))
            except: pass
        if token.startswith('+'):
            val = self._resolve(token[1:])
            try: return float(val) if val is not None else 0
            except: return 0
        # Try direct number first
        try: return float(token)
        except: pass
        # Resolve as expression
        val = self._resolve(token)
        if val is None: return 0
        try: return float(val)
        except: return 0

    def _eval_condition(self, cond: str) -> bool:
        """Evalúa una condición M: $DATA(x)=1, var>5, etc."""
        cond = cond.strip()
        if cond == "":
            return True  # condición vacía = verdadero en M

        # Operadores de comparación
        for op in [">=", "<=", "!=", "=", ">", "<"]:
            if op in cond:
                parts = cond.split(op, 1)
                left = self._resolve(parts[0].strip())
                right = self._resolve(parts[1].strip())
                try:
                    lv, rv = float(left), float(right)
                    if op == "=": return lv == rv
                    if op == "!=": return lv != rv
                    if op == ">": return lv > rv
                    if op == "<": return lv < rv
                    if op == ">=": return lv >= rv
                    if op == "<=": return lv <= rv
                except (ValueError, TypeError):
                    ls, rs = str(left), str(right)
                    if op == "=": return ls == rs
                    if op == "!=": return ls != rs
                    if op == ">": return ls > rs
                    if op == "<": return ls < rs
                    if op == ">=": return ls >= rs
                    if op == "<=": return ls <= rs

        # Negación
        if cond.startswith("'"):
            return not self._eval_condition(cond[1:])

        # Valor directo
        val = self._resolve(cond)
        return bool(val) if val is not None else False

    def _parse_subs(self, subs_str: str) -> list:
        """Parsea subíndices '42, "name"' → [42, 'name']"""
        subs = []
        for part in subs_str.split(","):
            part = part.strip()
            subs.append(self._resolve(part))
        return subs
