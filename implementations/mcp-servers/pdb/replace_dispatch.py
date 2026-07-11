"""Replace _exec_line with binary search dispatch."""
import sys

path = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb/m_light.py"
with open(path, 'r') as f:
    content = f.read()

# Find _exec_line boundaries
start = content.find("    def _exec_line(self, line: str) -> Any:")
end = content.find("\n    def _exec_for", start)

new_method = """    # ── Token Table (sorted for binary search, como MSM FUN_00494120) ──
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
        ("W", "WRITE",   "_exec_write"),
    ]

    def _dispatch_cmd(self, token):
        \"\"\"Binary search sobre TOKEN_TABLE (MSM FUN_00494120 pattern).\"\"\"
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
        \"\"\"Ejecuta una l\\xednea M. Dispatch via binary search (MSM token table).\"\"\"
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
            while pos < len(line) and line[pos] == ' ':
                pos += 1
            if pos >= len(line):
                break
            # Extraer token
            end = pos
            while end < len(line) and line[end] not in (' ', ':', '\\t'):
                end += 1
            token = line[pos:end]
            # Postconditional
            postcond = ""
            if end < len(line) and line[end] == ':':
                ce = end + 1
                while ce < len(line) and line[ce] not in (' ', '\\t'):
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
                        cv = self.eval_expr(postcond[1:])
                        if not cv:
                            continue
                    except:
                        pass
                result = handler(line, pos)
                if isinstance(result, int):
                    pos = result
                else:
                    break
            else:
                er = self.eval_expr(line[pos:])
                if er is not None:
                    return er
                break
        return result
"""

new_content = content[:start] + new_method + content[end:]
with open(path, 'w') as f:
    f.write(new_content)

print("OK: _exec_line replaced with binary search dispatch")
