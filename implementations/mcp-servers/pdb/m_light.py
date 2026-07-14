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

    def __init__(self, pdb_tools_module=None, device_manager=None, current_io=0):
        self.pdb = pdb_tools_module
        self.scope = MScope()
        self._quit_flag = False
        self._quit_stack = []  # stack para QUIT por nivel (FOR anidados)
        self._labels = {}
        self._label_mode = False
        self._goto_target = None
        self._call_stack = []
        self._do_call = False
        self._last_ref = None  # naked reference: {"ns": name, "subs": [...]}
        self._device_manager = device_manager  # DeviceManager para I/O
        self._current_io = current_io  # $IO — dispositivo activo
        # MSM job memory simulation for $V()
        self._job_memory = {}
        self._sys_memory = {
            -5: bytearray(512),
            -4: bytearray(512),
            -3: bytearray(2048),
            -2: bytearray(256),
        }
        sm3 = self._sys_memory[-3]
        sm3[0:2] = (4).to_bytes(2, 'little')
        sm3[2:4] = (2).to_bytes(2, 'little')
        sm5 = self._sys_memory[-5]
        sm5[3] = 2
        sm5[5] = 0
        sm5[7] = 4
        sm4 = self._sys_memory[-4]
        sm4[0:2] = (0x0b | 0x08).to_bytes(2, 'little')
        sm4[2:4] = (8).to_bytes(2, 'little')
        sm4[116:120] = (128).to_bytes(4, 'little')
        sm4[168:170] = (2).to_bytes(2, 'little')
        sm4[272:276] = (0).to_bytes(4, 'little')
        sm4[284] = 100
        sm4[287] = 90
        sm4[288:292] = (1000).to_bytes(4, 'little')
        sm4[304:308] = (10).to_bytes(4, 'little')
        self._job_memory[0] = bytearray(1200)
        jm0 = self._job_memory[0]
        jm0[6:8] = (1).to_bytes(2, 'little')
        jm0[8:10] = (1).to_bytes(2, 'little')
        jm0[44:46] = (0).to_bytes(2, 'little')

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

    # ── Token Table (sorted for binary search, como MSM FUN_00494120) ──
    TOKEN_TABLE = [
        ("C", "CLOSE",   "_exec_close"),
        ("D", "DO",      "_exec_do"),
        ("ELSE", "ELSE", "_exec_else"),
        ("F", "FOR",     "_exec_for"),
        ("G", "GOTO",    "_exec_goto"),
        ("I", "IF",      "_exec_if"),
        ("K", "KILL",    "_exec_kill"),
        ("N", "NEW",     "_exec_new"),
        ("O", "OPEN",    "_exec_open"),
        ("Q", "QUIT",    "_exec_quit"),
        ("R", "READ",    "_exec_read"),
        ("S", "SET",     "_exec_set"),
        ("U", "USE",     "_exec_use"),
        ("V", "VIEW",    "_exec_view"),
        ("W", "WRITE",   "_exec_write"),
        ("ZQ", "ZQ",     "_exec_zq"),
    ]

    def _dispatch_cmd(self, token):
        """Binary search sobre TOKEN_TABLE (MSM FUN_00494120 pattern)."""
        t = token.upper()
        lo, hi = 0, len(self.TOKEN_TABLE) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            short, full, method_name = self.TOKEN_TABLE[mid]
            if t == short or t == full:
                return getattr(self, method_name, None), full
            elif (t < short) if len(t) <= 1 else (t < full):
                hi = mid - 1
            else:
                lo = mid + 1
        return None, None

    def _exec_line(self, line: str) -> Any:
        """Ejecuta una línea M. Itera TODOS los comandos en la línea."""
        if not line or self._quit_flag:
            return None
        # Eliminar comentarios
        stripped = ''
        in_str = False
        for ch in line:
            if ch == '"':
                in_str = not in_str
                stripped += ch
            elif ch == ';' and not in_str:
                break
            else:
                stripped += ch
        line = stripped
        result = None
        pos = 0
        
        while pos < len(line) and not self._quit_flag:
            # Saltar whitespace
            while pos < len(line) and line[pos] == ' ':
                pos += 1
            if pos >= len(line):
                break
            
            # Extraer token comando
            end = pos
            while end < len(line) and line[end] not in (' ', ':', '\t'):
                end += 1
            token = line[pos:end]
            
            # Postconditional
            postcond = ""
            if end < len(line) and line[end] == ':':
                ce = end + 1
                while ce < len(line) and line[ce] not in (' ', '\t'):
                    ce += 1
                postcond = line[end:ce]
                end = ce
            
            handler, full = self._dispatch_cmd(token)
            if handler:
                pos = end
                while pos < len(line) and line[pos] == ' ':
                    pos += 1
                if postcond:
                    try:
                        cv = self._eval_condition(postcond[1:])
                        if not cv:
                            # Pos ya apunta al siguiente comando (pos=end + espacios)
                            continue
                    except:
                        pass
                result = handler(line, pos)
                if isinstance(result, int):
                    # Avanzar al siguiente comando usando _cmd_boundary
                    rest = line[result:]
                    boundary = self._cmd_boundary(rest)
                    if boundary < len(rest):
                        pos = result + boundary
                    else:
                        pos = result  # seguirá siendo len(line) → sale del while
                else:
                    break
            else:
                er = self.eval_expr(line[pos:])
                if er is not None:
                    return er
                break
        return result

    def _split_for_ranges(self, s: str):
        parts = []
        depth = 0
        current = ""
        for ch in s:
            if ch == ',' and depth == 0:
                parts.append(current)
                current = ""
            else:
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                current += ch
        if current:
            parts.append(current)
        return parts

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
        # FOR con variable: 'VAR=range1,range2,...'
        var_match = re.match(r'(\w+)\s*=\s*(.+)', line[pos:])
        if var_match:
            var_name = var_match.group(1)
            ranges_str = var_match.group(2)
            rest = line[pos + var_match.end():].strip()

            # Separar body del último rango
            body = ""
            depth = 0
            split_pos = -1
            for i, ch in enumerate(ranges_str):
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                elif ch == ' ' and depth == 0:
                    split_pos = i
                    break
            if split_pos >= 0:
                body = ranges_str[split_pos:].strip() + " " + rest
                ranges_str = ranges_str[:split_pos]
            elif rest:
                body = rest

            # Parsear rangos respetando paréntesis anidados
            range_parts = self._split_for_ranges(ranges_str)
            ranges = []
            for rp in range_parts:
                rp = rp.strip()
                parts = rp.split(':')
                if len(parts) == 3:
                    ranges.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
                elif len(parts) == 2:
                    ranges.append((parts[0].strip(), '1', parts[1].strip()))
                else:
                    ranges.append((rp, '0', rp))

            self._quit_stack.append(False)
            for start_str, step_str, end_str in ranges:
                start_val = float(self._resolve(start_str))
                step_val = float(self._resolve(step_str)) if step_str != '0' else 0
                end_val = float(self._resolve(end_str))
                val = start_val
                while True:
                    if self._quit_stack[-1]:
                        break
                    if step_val > 0 and val > end_val:
                        break
                    if step_val < 0 and val < end_val:
                        break
                    if step_val == 0:
                        child.set(var_name, val)
                    else:
                        child.set(var_name, val)
                    if body.startswith('{'):
                        block_end = self._find_block_end(body)
                        self._exec_line(body[1:block_end])
                    elif body:
                        self._exec_line(body)
                    if step_val == 0:
                        break
                    val += step_val
            self._quit_stack.pop()

        else:
            # FOR infinito: F  S N=$O(...) Q:cond
            body = line[pos:].strip()
            _max_iter = 100000
            _iter = 0
            self._quit_stack.append(False)
            while not self._quit_stack[-1] and _iter < _max_iter:
                _iter += 1
                if body.startswith('{'):
                    block_end = self._find_block_end(body)
                    self.eval(body[1:block_end])
                else:
                    self.eval(body)
            self._quit_stack.pop()

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

            # ^(subs)=value — naked reference SET (reemplaza último subíndice)
            naked_match = re.match(r'\^\(([^)]+)\)\s*=\s*(.+)', rest)
            if naked_match and self.pdb and self._last_ref:
                ns = self._last_ref["ns"]
                naked_subs = self._parse_subs(naked_match.group(1))
                # Reemplazar último subíndice de last_ref por los nuevos
                base = list(self._last_ref["subs"])
                if base and len(base) > 0:
                    subs = base[:-1] + naked_subs
                else:
                    subs = naked_subs
                value_expr = naked_match.group(2)
                value_end = self._cmd_boundary(value_expr)
                value = self._resolve(value_expr[:value_end].strip())
                self.pdb.tool_set({"ns": ns, "subs": subs, "value": value})
                self._last_ref = {"ns": ns, "subs": list(subs)}
                chunk = len(naked_match.group(0)) - (len(value_expr) - value_end)
                consumed += chunk
                rest = rest[chunk:]
                break

            # ^ns(subs)=value
            g_match = re.match(r'\^(\w+)\(([^)]+)\)\s*=\s*(.+)', rest)
            if g_match and self.pdb:
                ns = g_match.group(1)
                subs = self._parse_subs(g_match.group(2))
                value_expr = g_match.group(3)
                value_end = self._cmd_boundary(value_expr)
                value = self._resolve(value_expr[:value_end].strip())
                self._last_ref = {"ns": ns, "subs": list(subs)}
                self.pdb.tool_set({"ns": ns, "subs": subs, "value": value})
                chunk = len(g_match.group(0)) - (len(value_expr) - value_end)
                consumed += chunk
                rest = rest[chunk:]
                if rest.startswith(','):
                    rest = rest[1:]
                    consumed += 1
                    continue
                break

            # ^barename=value — global sin subíndices
            b_match = re.match(r'\^(\w+)\s*=\s*(.+)', rest)
            if b_match and self.pdb:
                ns = b_match.group(1)
                value_expr = b_match.group(2)
                value_end = self._cmd_boundary(value_expr)
                value = self._resolve(value_expr[:value_end].strip())
                self._last_ref = {"ns": ns, "subs": []}
                self.pdb.tool_set({"ns": ns, "subs": [], "value": value})
                chunk = len(b_match.group(0)) - (len(value_expr) - value_end)
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
        """Encuentra dónde termina el valor (antes del siguiente comando M o coma).
        Respeta strings con comillas dobles y simples, y paréntesis anidados."""
        depth = 0
        in_dq = False  # inside double-quoted string
        in_sq = False  # inside single-quoted string
        for i, ch in enumerate(s):
            if ch == '"' and not in_sq:
                # MUMPS: "" dentro de string es quote escapado
                if in_dq and i + 1 < len(s) and s[i + 1] == '"':
                    continue  # skip escaped quote
                in_dq = not in_dq
                continue
            if ch == "'" and not in_dq:
                in_sq = not in_sq
                continue
            if in_dq or in_sq:
                continue  # inside string, don't interpret separators
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif depth == 0 and (ch == ' ' or ch == ',' or ch == '}'):
                if ch in ',}':
                    return i
                # ch == ' '
                # Detectar siguiente comando M (mono o multi-letra)
                remain = s[i:].strip()
                if re.match(r'(?:DO|FOR|SET|KILL|QUIT|IF|ELSE|WRITE|GOTO|READ|NEW|OPEN|USE|CLOSE|BREAK|HALT|XECUTE|JOB|TSTART|TROLLBACK|TCOMMIT|TLEVEL|ZINSERT|ZLOAD|ZPRINT|ZREMOVE|ZSAVE)\b', remain):
                    return i
                if remain and remain[0] in 'FKSQIWDGRNUC' and (len(remain) == 1 or not remain[1].isalpha()):
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
                # Multi-letter commands
                if re.match(r'(?:DO|FOR|SET|KILL|QUIT|IF|ELSE|WRITE|GOTO|READ|NEW|OPEN|USE|CLOSE|BREAK|HALT|XECUTE|JOB|TSTART|TROLLBACK|TCOMMIT|TLEVEL|ZINSERT|ZLOAD|ZPRINT|ZREMOVE|ZSAVE)\b', rest):
                    return s[:i].strip()
                # Single-letter commands
                if rest and rest[0] in 'FKSQIWDGRNUC' and (len(rest) == 1 or not rest[1].isalpha()):
                    return s[:i].strip()
        return s.strip()

    # ── MSM $V() memory simulation ──

    def _msm_job_mem(self, job: int) -> bytearray:
        if job < 0:
            if job in self._sys_memory:
                return self._sys_memory[job]
            return bytearray(256)
        if job not in self._job_memory:
            self._job_memory[job] = bytearray(51200)
        return self._job_memory[job]

    def _msm_view(self, offset: int, job: int, size: int = 1) -> int:
        mem = self._msm_job_mem(job)
        if offset < 0 or offset >= len(mem):
            return 0
        if size == 0 or size == 2:
            if offset + 2 > len(mem): return 0
            return int.from_bytes(mem[offset:offset+2], 'little')
        elif size == 4:
            if offset + 4 > len(mem): return 0
            return int.from_bytes(mem[offset:offset+4], 'little')
        else:
            return mem[offset] if offset < len(mem) else 0

    def _msm_setview(self, offset: int, job: int, value: int, size: int = 1):
        mem = self._msm_job_mem(job)
        if offset < 0 or offset >= len(mem): return
        if size == 0 or size == 2:
            if offset + 2 <= len(mem):
                mem[offset:offset+2] = (value & 0xFFFF).to_bytes(2, 'little')
        elif size == 4:
            if offset + 4 <= len(mem):
                mem[offset:offset+4] = (value & 0xFFFFFFFF).to_bytes(4, 'little')
        else:
            mem[offset] = value & 0xFF

    def _exec_view(self, line: str, pos: int) -> int:
        rest = line[pos:].strip()
        m = re.match(r'(\d+):(-?\d+):(\d+):(\d+)', rest)
        if m:
            offset = int(m.group(1))
            job = int(m.group(2))
            value = int(m.group(3))
            size = int(m.group(4))
            self._msm_setview(offset, job, value, size)
            return pos + m.end()
        m2 = re.match(r'(\d+):(-?\d+):(\d+)', rest)
        if m2:
            offset = int(m2.group(1))
            job = int(m2.group(2))
            value = int(m2.group(3))
            self._msm_setview(offset, job, value, 1)
            return pos + m2.end()
        return len(line)

    def _exec_zq(self, line: str, pos: int) -> int:
        self._quit_flag = True
        return len(line)

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
        Usa _quit_stack para FOR anidados (cada nivel tiene su flag)."""
        if postcond and postcond.startswith(':'):
            cond = postcond[1:].strip()
            if self._eval_condition(cond):
                if self._quit_stack:
                    self._quit_stack[-1] = True
                else:
                    self._quit_flag = True
            return pos
        else:
            if self._quit_stack:
                self._quit_stack[-1] = True
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
        # Encontrar el final de la condición usando _cmd_boundary
        cond_end = self._cmd_boundary(rest)
        if cond_end > 0 and cond_end < len(rest):
            cond = rest[:cond_end].strip()
            cmd = rest[cond_end:].strip()
            if self._eval_condition(cond):
                self._exec_line(cmd)
        else:
            # Solo condición, evaluar
            self._eval_condition(rest)
        return len(line)

    # ── WRITE ──

    def _exec_write(self, line: str, pos: int) -> int:
        """WRITE — imprime expresiones al dispositivo activo ($IO)."""
        rest = line[pos:].strip()
        output = []

        # Dividir por comas solo en depth=0 (no dentro de paréntesis)
        items = []
        depth = 0
        current = ""
        for ch in rest:
            if ch == '(':
                depth += 1
                current += ch
            elif ch == ')':
                depth -= 1
                current += ch
            elif ch == ',' and depth == 0:
                items.append(current.strip())
                current = ""
            else:
                current += ch
        if current.strip():
            items.append(current.strip())

        for item in items:
            if not item: continue
            if item.replace('!', '') == '':
                n = len(item)
                output.append('\n' * n)
                self.scope.set('$Y', (self.scope.get('$Y') or 0) + n)
                self.scope.set('$X', 0)
            elif item.startswith('*'):
                try:
                    code = int(self._resolve(item[1:]))
                    ch = chr(code)
                    output.append(ch)
                    self.scope.set('$X', (self.scope.get('$X') or 0) + 1)
                except:
                    output.append(f'[{item}]')
            elif item.startswith('?'):
                try:
                    col = int(self._resolve(item[1:]))
                    cur_x = self.scope.get('$X') or 0
                    if col < cur_x:
                        output.append('\n')
                        self.scope.set('$Y', (self.scope.get('$Y') or 0) + 1)
                        cur_x = 0
                    output.append(' ' * (col - cur_x))
                    self.scope.set('$X', col)
                except:
                    output.append(f'[{item}]')
            else:
                val = self._resolve(item)
                s = str(val) if val is not None else ''
                output.append(s)
                # Update $X/$Y based on written content
                lines_in_output = s.count('\n')
                if lines_in_output:
                    self.scope.set('$Y', (self.scope.get('$Y') or 0) + lines_in_output)
                    self.scope.set('$X', len(s) - s.rfind('\n') - 1)
                else:
                    self.scope.set('$X', (self.scope.get('$X') or 0) + len(s))

        text = ''.join(output)
        # Rutear al dispositivo activo si hay DeviceManager
        if self._device_manager:
            self._device_manager.write(self._current_io, text)
        else:
            print(f'[M-Light WRITE] {text}')
        return len(line)

    def _exec_read(self, line: str, pos: int) -> int:
        """READ prompt:var — lee del dispositivo activo ($IO)."""
        rest = line[pos:].strip()
        # Parse READ: puede tener timeout (:N) y asterisco (*)
        # Formato: READ "prompt",var:timeout  o  READ *var  o  READ var
        if rest.startswith('*'):
            # READ *var — read single char
            var = rest[1:].strip()
            value = ' '
            if self._device_manager:
                value = self._device_manager.read(self._current_io, raw=True) or ' '
            self.scope.set(var, value)
            return len(line)
        # Split by comma at depth 0: "prompt",var:timeout
        items = []
        depth = 0
        current = ""
        for ch in rest:
            if ch == '(':
                depth += 1
                current += ch
            elif ch == ')':
                depth -= 1
                current += ch
            elif ch == ',' and depth == 0:
                items.append(current.strip())
                current = ""
            else:
                current += ch
        if current.strip():
            items.append(current.strip())

        for item in items:
            item = item.strip()
            if not item:
                continue
            # Check for timeout: var:timeout
            if ':' in item:
                # Could be "prompt":timeout or var:timeout
                parts = item.split(':')
                if len(parts) >= 2 and item.startswith('"') and item.count('"') >= 2:
                    # "prompt":timeout — write prompt but don't read
                    prompt_text = str(self._resolve(parts[0]))
                    if self._device_manager:
                        self._device_manager.write(self._current_io, prompt_text)
                    else:
                        pass  # no prompt output
                elif len(parts) == 2:
                    # var:timeout — read with timeout
                    var = parts[0].strip()
                    timeout = parts[1].strip()
                    # timeout 0 = non-blocking, just return empty
                    value = ''
                    if self._device_manager and timeout != '0':
                        value = self._device_manager.read(self._current_io).strip()
                    self.scope.set(var, value)
                elif len(parts) >= 2:
                    var = parts[0].strip()
                    value = ''
                    if self._device_manager:
                        value = self._device_manager.read(self._current_io).strip()
                    self.scope.set(var, value)
            elif item.startswith('"'):
                # Just a prompt string (write it)
                prompt_text = str(self._resolve(item))
                if self._device_manager:
                    self._device_manager.write(self._current_io, prompt_text)
            else:
                # Plain variable read
                var = item.strip()
                value = ''
                if self._device_manager:
                    value = self._device_manager.read(self._current_io).strip()
                self.scope.set(var, value)
        return len(line)

    def _exec_new(self, line, pos):
        for v in line[pos:].strip().replace(',',' ').split():
            self.scope.vars.pop(v.strip(), None)
        return len(line)

    def _exec_open(self, line, pos):
        """OPEN device:params — abre un dispositivo I/O."""
        rest = line[pos:].strip()
        # Parse "OPEN 8:params" or "OPEN 8"
        if self._device_manager:
            parts = rest.split(":", 1)
            try:
                dev_num = int(parts[0].strip())
            except ValueError:
                return len(line)
            params = parts[1].strip() if len(parts) > 1 else ""
            self._device_manager.open(dev_num, params)
        return len(line)

    def _exec_use(self, line, pos):
        """USE device — cambia $IO al dispositivo indicado."""
        rest = line[pos:].strip()
        try:
            dev_num = int(rest)
            self._current_io = dev_num
        except ValueError:
            pass
        return len(line)

    def _exec_close(self, line, pos):
        """CLOSE device — cierra un dispositivo I/O."""
        rest = line[pos:].strip()
        if self._device_manager:
            try:
                dev_num = int(rest)
                self._device_manager.close(dev_num)
            except ValueError:
                pass
        return len(line)

    # ── Helper: dividir argumentos por coma respetando paréntesis ──
    # Necesario para $P($G(...),...) y otras funciones anidadas
    def _split_args_by_parens(self, s: str) -> list:
        args = []
        depth = 0
        current = ""
        in_string = False
        str_char = None
        for c in s:
            if in_string:
                current += c
                if c == str_char:
                    in_string = False
                continue
            if c in ('"', "'"):
                in_string = True
                str_char = c
                current += c
                continue
            if c == '(':
                depth += 1
                current += c
            elif c == ')':
                depth -= 1
                current += c
            elif c == ',' and depth == 0:
                args.append(current.strip())
                current = ""
            else:
                current += c
        if current.strip():
            args.append(current.strip())
        return args

    # ── Evaluación de expresiones ──

    def _resolve(self, token: str) -> Any:
        """Resuelve un token: expresión $, variable, literal."""
        token = token.strip()

        # _ concatenación — debe ir PRIMERO para evitar que $ funciones
        # capturen todo (ej: $C(27)_"[6" no debe ser interpretado como solo $C)
        if '_' in token:
            depth = 0
            for i, ch in enumerate(token):
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                elif ch == '_' and depth == 0:
                    left = token[:i].strip()
                    right = token[i+1:].strip()
                    if left and right:
                        lv = str(self._resolve(left))
                        rv = str(self._resolve(right))
                        return lv + rv

        # $GET(^ns(subs)) — también $G (soporta multi-nivel)
        m = re.match(r'\$(?:GET|G)\s*\(\^(\w+)\((.+?)\)\s*\)', token)
        if m and self.pdb:
            ns = m.group(1)
            subs = self._parse_subs(m.group(2))
            self._last_ref = {"ns": ns, "subs": list(subs)}
            r = self.pdb.tool_get({"ns": ns, "subs": subs})
            return r.get("value")

        # $GET(^barename) — $G con global sin subíndices
        m = re.match(r'\$(?:GET|G)\s*\(\^(\w+)\)\s*', token)
        if m and self.pdb:
            ns = m.group(1)
            self._last_ref = {"ns": ns, "subs": []}
            r = self.pdb.tool_get({"ns": ns, "subs": []})
            return r.get("value")

        # $GET(var) — $G con variable local
        m = re.match(r'\$(?:GET|G)\s*\((\w+)\)', token)
        if m:
            var = self.scope.get(m.group(1))
            return var if var is not None else ""

        # $DATA(^ns(subs)) — también $D (soporta multi-nivel)
        m = re.match(r'\$(?:DATA|D)\s*\(\^(\w+)\((.+?)\)\s*\)', token)
        if m and self.pdb:
            ns = m.group(1)
            subs = self._parse_subs(m.group(2))
            self._last_ref = {"ns": ns, "subs": list(subs)}
            r = self.pdb.tool_data({"ns": ns, "subs": subs})
            return r.get("value", 0)

        # $ORDER(^ns(subs), dir) — el alma de M (también $O)
        m = re.match(r'\$(?:ORDER|O)\s*\(\^(\w+)\(([^)]+)\)\s*(?:,\s*([-]?\d+))?\s*\)', token)
        if m and self.pdb:
            ns = m.group(1)
            subs = self._parse_subs(m.group(2))
            direction = int(m.group(3)) if m.group(3) else 1
            self._last_ref = {"ns": ns, "subs": list(subs)}
            r = self.pdb.tool_order({"ns": ns, "subs": subs, "direction": direction})
            # MUMPS $ORDER returns "" (empty string) when no more elements
            val = r.get("value")
            return val if val is not None else ""

        # $PIECE(string, delim, n) — también $P (con paréntesis anidados)
        m = re.match(r'\$(?:PIECE|P)\s*\((.+)\)\s*$', token)
        if m:
            args = self._split_args_by_parens(m.group(1))
            if len(args) >= 3:
                string = self._resolve(args[0])
                delim = args[1].strip().strip("'\"")
                n = int(self._resolve(args[2]))
                parts = str(string).split(delim)
                return parts[n-1] if n <= len(parts) else ""

        # $EXTRACT(string, from, to?) — también $E (con paréntesis anidados)
        m = re.match(r'\$(?:EXTRACT|E)\s*\((.+)\)\s*$', token)
        if m:
            args = self._split_args_by_parens(m.group(1))
            if len(args) >= 2:
                string = str(self._resolve(args[0]))
                frm = int(self._resolve(args[1])) - 1
                to = int(self._resolve(args[2])) if len(args) >= 3 else frm + 1
                return string[frm:to]

        # $SELECT(cond1:val1, ..., 1:default) — también $S
        m = re.match(r'\$(?:SELECT|S)\s*\(\s*(.+)\s*\)', token)
        if m:
            pairs = self._split_args_by_parens(m.group(1))
            for pair in pairs:
                if ":" in pair:
                    cond, val = pair.split(":", 1)
                    if self._eval_condition(cond.strip()):
                        return self._resolve(val.strip())
            return None

        # $LENGTH(string [,delim]) — también $L
        m = re.match(r'\$(?:LENGTH|L)\s*\((.+)\)\s*$', token)
        if m:
            args = self._split_args_by_parens(m.group(1))
            val = str(self._resolve(args[0]))
            if len(args) >= 2:
                delim = args[1].strip().strip("'\"")
                return len(val.split(delim))
            return len(val)

        # $FIND(string,substring) — también $F
        m = re.match(r'\$(?:FIND|F)\s*\((.+)\)\s*$', token)
        if m:
            args = self._split_args_by_parens(m.group(1))
            if len(args) >= 2:
                haystack = str(self._resolve(args[0]))
                needle = str(self._resolve(args[1]))
                pos = haystack.find(needle)
                return pos + len(needle) + 1 if pos >= 0 else 0

        # $CHAR(code1,code2,...) — también $C. Devuelve string con caracteres
        m = re.match(r'\$(?:CHAR|C)\s*\(\s*(.+)\s*\)', token)
        if m:
            codes = []
            for arg in self._split_args_by_parens(m.group(1)):
                arg = arg.strip()
                codes.append(int(self._resolve(arg)))
            return ''.join(chr(c) for c in codes)

        # System variables: $J (job), $H (horolog), $IO (device)
        if token == '$J':
            # $J = $JOB (job number), $J(...) = $JUSTIFY
            return self.scope.get('$J') or '0'
        # $JUSTIFY(string, width [,decimal]) — también $J()
        m = re.match(r'\$(?:JUSTIFY|J)\s*\((.+)\)\s*$', token)
        if m:
            args = self._split_args_by_parens(m.group(1))
            val = str(self._resolve(args[0]))
            width = int(self._resolve(args[1])) if len(args) >= 2 else 0
            decimal = int(self._resolve(args[2])) if len(args) >= 3 else -1
            if decimal >= 0:
                try: return str(round(float(val), decimal)).rjust(width)
                except: return val.rjust(width)
            return val.rjust(width)
        if token == '$H':
            import time, datetime
            now = datetime.datetime.now()
            epoch = datetime.datetime(1840, 12, 31)
            days = (now - epoch).days
            seconds = now.hour * 3600 + now.minute * 60 + now.second
            return f"{days},{seconds}"
        if token == '$IO':
            return self.scope.get('$IO') or '0'
        if token == '$ZV':
            return 'LUMEN M-Light v1.0'
        # $ZMSM(code, ...) — MSM system info stub
        m = re.match(r'\$ZMSM\s*\(\s*(.+)\s*\)\s*$', token)
        if m:
            return 0  # stub — return 0 for all $ZMSM calls

        # $ZB(expr, start, count) — bit field extraction
        m = re.match(r'\$ZB\s*\(\s*(.+)\s*\)\s*$', token)
        if m:
            args = self._split_args_by_parens(m.group(1))
            if len(args) >= 3:
                expr = int(self._resolve(args[0]))
                start = int(self._resolve(args[1]))
                count = int(self._resolve(args[2]))
                mask = (1 << count) - 1
                return (expr >> start) & mask
            return 0

        # $V(offset, job, size) — memory peek
        m = re.match(r'\$V\s*\(\s*(.+)\s*\)\s*$', token)
        if m:
            args = self._split_args_by_parens(m.group(1))
            if len(args) >= 2:
                offset = int(self._resolve(args[0]))
                job = int(self._resolve(args[1]))
                size = int(self._resolve(args[2])) if len(args) >= 3 else 1
                return self._msm_view(offset, job, size)

        if token == '$X':
            return int(self.scope.get('$X') or 0)
        if token == '$Y':
            return int(self.scope.get('$Y') or 0)

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

        # ^(subs) — naked reference (reemplaza último subíndice)
        m = re.match(r'\^\(([^)]+)\)', token)
        if m and self.pdb and self._last_ref:
            ns = self._last_ref["ns"]
            naked_subs = self._parse_subs(m.group(1))
            base = list(self._last_ref["subs"])
            if base and len(base) > 0:
                subs = base[:-1] + naked_subs
            else:
                subs = naked_subs
            self._last_ref = {"ns": ns, "subs": list(subs)}
            r = self.pdb.tool_get({"ns": ns, "subs": subs})
            return r.get("value")

        # ^ns(subs) — acceso directo a global
        m = re.match(r'\^(\w+)\(([^)]+)\)', token)
        if m and self.pdb:
            ns = m.group(1)
            subs = self._parse_subs(m.group(2))
            self._last_ref = {"ns": ns, "subs": list(subs)}  # para naked reference
            r = self.pdb.tool_get({"ns": ns, "subs": subs})
            return r.get("value")

        # ^barename — acceso directo a global sin subíndices
        m = re.match(r'\^(\w+)$', token)
        if m and self.pdb:
            ns = m.group(1)
            self._last_ref = {"ns": ns, "subs": []}
            r = self.pdb.tool_get({"ns": ns, "subs": []})
            return r.get("value")

        # @(expr) — indirección M (evalúa expr y usa el resultado como código)
        m = re.match(r'@\((.+)\)', token)
        if m:
            inner = self._resolve(m.group(1))
            if inner and isinstance(inner, str):
                return self._resolve(inner)
            return inner

        # Variable local — M devuelve "" para variables no inicializadas
        val = self.scope.get(token)
        if val is not None:
            return val
        # Variable no definida en M = cadena vacía
        if re.match(r'^[A-Z][A-Z0-9]*$', token, re.IGNORECASE):
            return ""

        # Literal — DEBE IR ANTES del bloque aritmético (que detecta # como módulo)
        if token.startswith('"') and token.endswith('"'):
            return token[1:-1]
        if token.startswith("'") and token.endswith("'"):
            return token[1:-1]

        # Arithmetic expression — MUMPS evalúa left-to-right SIN precedencia
        # Soporta: +, -, *, /, \\ (div), # (mod), ** (exp)
        # Ej: T+$G(^X(I)), 5*$G(^A)+$G(^B), I\\100000#10*2
        # Busca operadores fuera de paréntesis (depth=0)
        # Strip outer parentheses for arithmetic evaluation
        stripped = token
        while stripped.startswith('(') and stripped.endswith(')'):
            inner = stripped[1:-1].strip()
            depth = 0
            balanced = True
            for c in inner:
                if c == '(': depth += 1
                elif c == ')': depth -= 1
                if depth < 0: balanced = False; break
            if balanced and depth == 0:
                stripped = inner
            else:
                break
        if any(op in stripped for op in ['\\','#','*','/','+','-']):
            # Find operators at depth=0
            depth = 0
            ops_at_depth0 = []
            # Check operators in order: ** first, then \\, #, *, /, +, -
            # (MUMPS is left-to-right, but we split on outermost operators)
            for i, ch in enumerate(stripped):
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                elif depth == 0:
                    if ch == '+' or ch == '-':
                        # Skip unary: if it's the first char or after another operator
                        if i == 0 or stripped[i-1] in ('*', '/', '\\', '#', '(', '+', '-'):
                            continue
                        ops_at_depth0.append((i, ch))
                    elif ch in ('*', '/', '\\', '#'):
                        ops_at_depth0.append((i, ch))
            
            if ops_at_depth0:
                # Take the LAST operator at depth 0 (rightmost = left-to-right eval)
                pos, op = ops_at_depth0[-1]
                left = stripped[:pos].strip()
                right = stripped[pos+1:].strip()
                if left and right:
                    lv = self._resolve_num(left)
                    rv = self._resolve_num(right)
                    if op == '+': result = lv + rv
                    elif op == '-': result = lv - rv
                    elif op == '*': result = lv * rv
                    elif op == '/': result = lv / rv if rv != 0 else 0
                    elif op == '\\': result = int(lv // rv) if rv != 0 else 0
                    elif op == '#': result = int(lv % rv) if rv != 0 else 0
                    return int(result) if result == int(result) else result

        # ^ns(subs) — referencia directa a global (soporta multi-nivel)
        m = re.match(r'\^(\w+)\((.+?)\)', token)
        if m and self.pdb:
            ns = m.group(1)
            subs = self._parse_subs(m.group(2))
            self._last_ref = {"ns": ns, "subs": list(subs)}
            r = self.pdb.tool_get({"ns": ns, "subs": subs})
            return r.get("value")

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

        # Negación — debe ir ANTES de operadores para evitar 'X=3
        if cond.startswith("'"):
            return not self._eval_condition(cond[1:])

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

        # Valor directo
        val = self._resolve(cond)
        return bool(val) if val is not None else False

    def _parse_subs(self, subs_str: str) -> list:
        """Parsea subíndices '42, "name"' → [42, 'name'].
        Respeta strings literales — NO evalúa aritmética en strings."""
        subs = []
        for part in subs_str.split(","):
            part = part.strip()
            # Si es string literal, devolver tal cual (sin evaluar aritmética)
            if (part.startswith('"') and part.endswith('"')) or \
               (part.startswith("'") and part.endswith("'")):
                subs.append(part[1:-1])
            else:
                subs.append(self._resolve(part))
        return subs
