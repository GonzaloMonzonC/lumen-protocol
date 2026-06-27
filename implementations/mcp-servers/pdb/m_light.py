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

    # ── API pública ──

    def eval(self, code: str) -> Any:
        """Evaluar una línea o bloque de código M."""
        self._quit_flag = False
        return self._exec_line(code.strip())

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
            cmd_match = re.match(r'(F(?:OR)?|S(?:ET)?|K(?:ILL)?|Q(?:UIT)?|IF|ELSE|W(?:RITE)?|D(?:O)?)((?:[:][^ ]+)?)\s', line[pos:])
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
                    pos = self._exec_quit(line, pos)
                elif cmd in ('I',):
                    pos = self._exec_if(line, pos)
                elif cmd in ('W',):
                    pos = self._exec_write(line, pos)
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
            # Buscar el cuerpo: todo hasta el final
            while not self._quit_flag:
                old_quit = self._quit_flag
                if body.startswith('{'):
                    block_end = self._find_block_end(body)
                    self._exec_line(body[1:block_end])
                else:
                    self._exec_line(body)
                if self._quit_flag or old_quit:
                    break

        self.scope = old_scope
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
        """SET var=value o SET ^ns(subs)=value"""
        rest = line[pos:].strip()

        # ^ns(subs)=value
        g_match = re.match(r'\^(\w+)\(([^)]+)\)\s*=\s*(.+)', rest)
        if g_match and self.pdb:
            ns = g_match.group(1)
            subs = self._parse_subs(g_match.group(2))
            value_str = g_match.group(3).strip()
            # Separar el valor del siguiente comando (dos espacios o fin de línea)
            value = self._resolve(self._until_next_cmd(value_str))
            self.pdb.tool_set({"ns": ns, "subs": subs, "value": value})
            return len(line)

        # var=value
        v_match = re.match(r'(\w+)\s*=\s*(.+)', rest)
        if v_match:
            var = v_match.group(1)
            value_str = v_match.group(2).strip()
            value = self._resolve(self._until_next_cmd(value_str))
            self.scope.set(var, value)
            return len(line)

        return pos + 1

    def _until_next_cmd(self, s: str) -> str:
        """Extrae el valor hasta el siguiente comando (dos espacios o fin)."""
        # Buscar el patrón de dos espacios seguidos de un comando
        m = re.match(r'(.*?)\s{2,}(?:F|S|K|Q|IF|ELSE|W|D)\b', s)
        if m:
            return m.group(1).strip()
        return s.strip()

    # ── KILL ──

    def _exec_kill(self, line: str, pos: int) -> int:
        """KILL ^ns(subs)"""
        rest = line[pos:].strip()
        g_match = re.match(r'\^(\w+)\(([^)]+)\)', rest)
        if g_match and self.pdb:
            ns = g_match.group(1)
            subs = self._parse_subs(g_match.group(2))
            self.pdb.tool_kill({"ns": ns, "subs": subs})
        return len(line)

    # ── QUIT ──

    def _exec_quit(self, line: str, pos: int) -> int:
        """QUIT[:condition] — sale del bucle actual si se cumple la condición"""
        rest = line[pos:].strip()
        cond_match = re.match(r':(.+)', rest)
        if cond_match:
            cond = cond_match.group(1).strip()
            if self._eval_condition(cond):
                self._quit_flag = True
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
            body_start = if_match.end() - 1  # apunta al {
            block_end = self._find_block_end(rest[body_start:])
            if self._eval_condition(cond):
                self._exec_line(rest[body_start+1:body_start+block_end])
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
        """WRITE expresión — imprime (útil para debug)"""
        rest = line[pos:].strip()
        val = self._resolve(rest)
        print(f"[M-Light WRITE] {val}")
        return len(line)

    # ── Evaluación de expresiones ──

    def _resolve(self, token: str) -> Any:
        """Resuelve un token: expresión $, variable, literal."""
        token = token.strip()

        # $GET(^ns(subs))
        m = re.match(r'\$GET\s*\(\^(\w+)\(([^)]+)\)\s*\)', token)
        if m and self.pdb:
            ns = m.group(1)
            subs = self._parse_subs(m.group(2))
            r = self.pdb.tool_get({"ns": ns, "subs": subs})
            return r.get("value")

        # $DATA(^ns(subs))
        m = re.match(r'\$DATA\s*\(\^(\w+)\(([^)]+)\)\s*\)', token)
        if m and self.pdb:
            ns = m.group(1)
            subs = self._parse_subs(m.group(2))
            r = self.pdb.tool_data({"ns": ns, "subs": subs})
            return r.get("value", 0)

        # $ORDER(^ns(subs), dir) — el alma de M
        m = re.match(r'\$ORDER\s*\(\^(\w+)\(([^)]+)\)\s*(?:,\s*([-]?\d+))?\s*\)', token)
        if m and self.pdb:
            ns = m.group(1)
            subs = self._parse_subs(m.group(2))
            direction = int(m.group(3)) if m.group(3) else 1
            r = self.pdb.tool_order({"ns": ns, "subs": subs, "direction": direction})
            return r.get("value")

        # $PIECE(string, delim, n)
        m = re.match(r'\$PIECE\s*\(\s*([^,]+)\s*,\s*["\']([^"\']+)["\']\s*,\s*(\d+)\s*\)', token)
        if m:
            string = self._resolve(m.group(1))
            delim = m.group(2)
            n = int(m.group(3))
            parts = str(string).split(delim)
            return parts[n-1] if n <= len(parts) else ""

        # $EXTRACT(string, from, to?)
        m = re.match(r'\$EXTRACT\s*\(\s*([^,]+)\s*,\s*(\d+)(?:\s*,\s*(\d+))?\s*\)', token)
        if m:
            string = str(self._resolve(m.group(1)))
            frm = int(m.group(2)) - 1
            to = int(m.group(3)) if m.group(3) else frm + 1
            return string[frm:to]

        # $SELECT(cond1:val1, ..., 1:default)
        m = re.match(r'\$SELECT\s*\(\s*(.+)\s*\)', token)
        if m:
            pairs = m.group(1).split(",")
            for pair in pairs:
                pair = pair.strip()
                if ":" in pair:
                    cond, val = pair.split(":", 1)
                    if self._eval_condition(cond.strip()):
                        return self._resolve(val.strip())
            return None

        # Variable local
        if token in self.scope.vars or (self.scope.parent and token in self.scope.parent.vars):
            return self.scope.get(token)

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
