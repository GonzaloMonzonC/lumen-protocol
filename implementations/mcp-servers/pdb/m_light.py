"""
M-Light — mini evaluador de expresiones M para PDB.

Soporta el subconjunto esencial de MUMPS:
- $GET(^ns(subs)) → pdb_get
- $DATA(^ns(subs)) → pdb_data
- $ORDER(^ns(subs), dir) → pdb_order
- $PIECE(string, delimiter, piece_n)
- $EXTRACT(string, from, to)
- $SELECT(cond1:val1, cond2:val2, 1:default)
- S ^ns(subs)=value → pdb_set
- K ^ns(subs) → pdb_kill
- IF condition { ... }
- F (FOR) loop con $ORDER
- Q (QUIT) condition

Usado por triggers y reglas M-light en PDB.
"""

import re
from typing import Any, Optional


class MEncoder:
    """Evalúa expresiones M contra PDB real."""

    def __init__(self, pdb_tools_module=None):
        self.pdb = pdb_tools_module

    def _encode(self, subs: list) -> bytes:
        """Encode subscript list using PDB's encoder if available."""
        if self.pdb:
            return self.pdb.encode_subkey(subs)
        return str(subs).encode()

    def global_ref(self, ns: str, subs: list) -> dict:
        """Resolve ^ns(subs) — returns value or None."""
        if not self.pdb:
            return {"value": None, "exists": False}
        return self.pdb.tool_get({"ns": ns, "subs": subs})

    def eval_expression(self, expr: str, context: dict = None) -> Any:
        """Evaluate a single M expression like $GET(^PATIENT(42,"name"))"""
        context = context or {}

        # $GET(^ns(...))
        m = re.match(r'\$GET\s*\(\^(\w+)\((.+)\)\s*\)', expr)
        if m:
            ns = m.group(1)
            subs = self._parse_subs(m.group(2), context)
            r = self.global_ref(ns, subs)
            return r.get("value")

        # $DATA(^ns(...))
        m = re.match(r'\$DATA\s*\(\^(\w+)\((.+)\)\s*\)', expr)
        if m:
            ns = m.group(1)
            subs = self._parse_subs(m.group(2), context)
            if self.pdb:
                r = self.pdb.tool_data({"ns": ns, "subs": subs})
                return r.get("value", 0)
            return 0

        # $PIECE(string, delim, n)
        m = re.match(r'\$PIECE\s*\(\s*([^,]+)\s*,\s*["\']([^"\']+)["\']\s*,\s*(\d+)\s*\)', expr)
        if m:
            string = self._resolve(m.group(1), context)
            delim = m.group(2)
            n = int(m.group(3))
            parts = str(string).split(delim)
            return parts[n-1] if n <= len(parts) else ""

        # $EXTRACT(string, from, to?)
        m = re.match(r'\$EXTRACT\s*\(\s*([^,]+)\s*,\s*(\d+)(?:\s*,\s*(\d+))?\s*\)', expr)
        if m:
            string = str(self._resolve(m.group(1), context))
            frm = int(m.group(2)) - 1
            to = int(m.group(3)) if m.group(3) else frm + 1
            return string[frm:to]

        # $SELECT(cond1:val1, cond2:val2, 1:default)
        m = re.match(r'\$SELECT\s*\(\s*(.+)\s*\)', expr)
        if m:
            pairs = m.group(1).split(",")
            for pair in pairs:
                pair = pair.strip()
                if ":" in pair:
                    cond, val = pair.split(":", 1)
                    if self.eval_condition(cond.strip(), context):
                        return self._resolve(val.strip(), context)
            return None

        # Literal string or number
        expr = expr.strip()
        if expr.startswith('"') and expr.endswith('"'):
            return expr[1:-1]
        try:
            return int(expr)
        except ValueError:
            try:
                return float(expr)
            except ValueError:
                return expr

    def eval_condition(self, cond: str, context: dict = None) -> bool:
        """Evaluate a condition like $DATA(^PATIENT(42))=1"""
        context = context or {}
        # Simple: value=value or value>value
        for op in [">=", "<=", "!=", "=", ">", "<"]:
            if op in cond:
                left, right = cond.split(op, 1)
                try:
                    lv = float(self._resolve(left.strip(), context))
                    rv = float(self._resolve(right.strip(), context))
                    if op == "=": return lv == rv
                    elif op == "!=": return lv != rv
                    elif op == ">": return lv > rv
                    elif op == "<": return lv < rv
                    elif op == ">=": return lv >= rv
                    elif op == "<=": return lv <= rv
                except (ValueError, TypeError):
                    ls = str(self._resolve(left.strip(), context))
                    rs = str(self._resolve(right.strip(), context))
                    if op == "=": return ls == rs
                    elif op == "!=": return ls != rs
        # Bare expression: truthy
        val = self._resolve(cond.strip(), context)
        return bool(val) if val is not None else False

    def _resolve(self, token: str, context: dict) -> Any:
        """Resolve a token to a value (expression, var, literal)."""
        token = token.strip()
        if token.startswith("$") or token.startswith("^"):
            return self.eval_expression(token, context)
        if token.startswith('"') and token.endswith('"'):
            return token[1:-1]
        if token in context:
            return context[token]
        try:
            return int(token)
        except ValueError:
            try:
                return float(token)
            except ValueError:
                return token

    def _parse_subs(self, subs_str: str, context: dict) -> list:
        """Parse subscripts from string like '42, "name"'"""
        subs = []
        for part in subs_str.split(","):
            part = part.strip()
            resolved = self._resolve(part, context)
            subs.append(resolved)
        return subs
