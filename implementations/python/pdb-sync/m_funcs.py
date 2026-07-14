#!/usr/bin/env python3
"""m_funcs.py — Runtime Function Table para M-Light v2.

$functions nativas sin regex, dispatch O(log n).
Inspirado en MSM std_func_handler + func_lookup.
"""

import sys, os, time
import _paths  # rutas repo-relativas
from typing import Any, Optional

# ═══════════════════════════════════════════════════
# 1. IMPLEMENTACIONES NATIVAS
# ═══════════════════════════════════════════════════

def func_piece(args):
    s = str(args[0]) if args else ""
    d = str(args[1]) if len(args) > 1 else ","
    n = int(args[2]) if len(args) > 2 else 1
    if n <= 0 or not s: return ""
    if not d: return s
    start = 0
    for i in range(1, n):
        pos = s.find(d, start)
        if pos < 0: return ""
        start = pos + len(d)
    end = s.find(d, start)
    return s[start:] if end < 0 else s[start:end]

def func_extract(args):
    s = str(args[0]) if args else ""
    fr = max(1, int(args[1])) if len(args) > 1 else 1
    to = min(int(args[2]), len(s)) if len(args) > 2 else fr
    if fr > len(s) or fr > to: return ""
    return s[fr-1:to]

def func_get(args, vm=None):
    ref = str(args[0]) if args else ""
    default = args[1] if len(args) > 1 else ""
    if vm and ref in vm.vars: return vm.vars[ref]
    if ref.startswith("^"):
        try:
            sp = _paths.PDB_DIR_S
            if sp not in sys.path: sys.path.insert(0, sp)
            from pdb_tools import tool_get
            if '(' in ref:
                ns = ref[1:ref.index('(')]
                ss = ref[ref.index('(')+1:ref.rindex(')')]
                subs = [s.strip().strip('"') for s in ss.split(',')]  # keep empty
                r = tool_get({"ns": ns, "subs": subs})
                if r.get("success") and r.get("value") is not None: return r["value"]
        except: pass
        return default
    return default

def func_ascii(args):
    s = str(args[0]) if args else ""
    p = int(args[1]) if len(args) > 1 else 1
    if not s or p < 1 or p > len(s): return -1
    return ord(s[p-1])

def func_char(args):
    res = ""
    for a in args:
        try: res += chr(int(a))
        except: res += "?"
    return res

def func_length(args):
    return len(str(args[0])) if args else 0

def func_find(args):
    s = str(args[0]) if args else ""
    sub = str(args[1]) if len(args) > 1 else ""
    if not sub: return 1
    pos = s.find(sub)
    return 0 if pos < 0 else pos + len(sub)

def func_select(args):
    for a in args:
        parts = str(a).split(':', 1)
        if len(parts) == 2:
            try:
                if float(parts[0]) != 0 or parts[0] == "1": return parts[1]
            except:
                if parts[0].strip(): return parts[1]
    return ""

func_translate_locals = None  # placeholder
def func_translate(args):
    s = str(args[0]) if args else ""
    fr = str(args[1]) if len(args) > 1 else ""
    to = str(args[2]) if len(args) > 2 else ""
    if not fr: return s
    table = {c: to[i] if i < len(to) else "" for i, c in enumerate(fr)}
    return "".join(table.get(c, c) for c in s)

# ═══════════════════════════════════════════════════
# 2. FUNCTION TABLE (sorted para binary search)
# ═══════════════════════════════════════════════════

FUNC_TABLE = [
    ("$A", 1, 2, func_ascii),
    ("$C", 1, 99, func_char),
    ("$D", 1, 1, None),
    ("$E", 1, 3, func_extract),
    ("$F", 2, 2, func_find),
    ("$G", 1, 2, func_get),
    ("$L", 1, 1, func_length),
    ("$O", 1, 2, None),
    ("$P", 2, 4, func_piece),
    ("$S", 2, 99, func_select),
    ("$TR", 3, 3, func_translate),
]

def func_dispatch(name):
    lo, hi = 0, len(FUNC_TABLE) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        n, _, _, _ = FUNC_TABLE[mid]
        if name == n: return FUNC_TABLE[mid]
        elif name < n: hi = mid - 1
        else: lo = mid + 1
    return None

def func_data(args):
    if not args: return 0
    try:
        sp = _paths.PDB_DIR_S
        if sp not in sys.path: sys.path.insert(0, sp)
        from pdb_tools import tool_data
        ref = str(args[0])
        if ref.startswith("^") and '(' in ref:
            ns = ref[1:ref.index('(')]
            ss = ref[ref.index('(')+1:ref.rindex(')')]
            subs = [s.strip().strip('"') for s in ss.split(',')]  # keep empty
            r = tool_data({"ns": ns, "subs": subs})
            if r.get("success"): return r.get("value", 0)
    except: pass
    return 0

def func_order(args):
    if not args: return ""
    try:
        sp = _paths.PDB_DIR_S
        if sp not in sys.path: sys.path.insert(0, sp)
        from pdb_tools import tool_order
        ref = str(args[0])
        if ref.startswith("^") and '(' in ref:
            ns = ref[1:ref.index('(')]
            ss = ref[ref.index('(')+1:ref.rindex(')')]
            parts = [s.strip().strip('"') for s in ss.split(',')]
            # Último elemento es el starting key, no un subíndice
            start_key = parts[-1] if parts else ""
            base = parts[:-1]
            r = tool_order({"ns": ns, "subs": base + [start_key], "direction": 1})
            if r.get("success"): return r.get("value", "")
    except: pass
    return ""

# Update table with actual handlers
FUNC_TABLE = [
    ("$A", 1, 2, func_ascii),
    ("$C", 1, 99, func_char),
    ("$D", 1, 1, func_data),
    ("$E", 1, 3, func_extract),
    ("$F", 2, 2, func_find),
    ("$G", 1, 2, func_get),
    ("$L", 1, 1, func_length),
    ("$O", 1, 2, func_order),
    ("$P", 2, 4, func_piece),
    ("$S", 2, 99, func_select),
    ("$TR", 3, 3, func_translate),
]

# ═══════════════════════════════════════════════════
# 3. EVALUATOR
# ═══════════════════════════════════════════════════

def _parse_args(raw):
    args = []; cur = ""; instr = False; depth = 0
    # Strip outer parens si existen
    raw = raw.strip()
    if raw.startswith('(') and raw.endswith(')'):
        raw = raw[1:-1]
    for ch in raw:
        if ch == '"': instr = not instr; cur += ch
        elif ch == '(' and not instr: depth += 1; cur += ch
        elif ch == ')' and not instr: depth -= 1; cur += ch
        elif ch == ',' and not instr and depth == 0:
            args.append(cur.strip()); cur = ""
        else: cur += ch
    if cur.strip(): args.append(cur.strip())
    cleaned = []
    for a in args:
        if a.startswith('"') and a.endswith('"'): cleaned.append(a[1:-1])
        else: cleaned.append(a)
    return cleaned

def eval_function(name, raw_args, vm=None):
    entry = func_dispatch(name)
    if not entry: return f"[UNKNOWN {name}]"
    _, min_ar, max_ar, handler = entry
    args = _parse_args(raw_args)
    if len(args) < min_ar:
        return f"[{name}: needed {min_ar}, got {len(args)}]"
    try:
        if name in ("$G", "$GET"): return handler(args, vm)
        return handler(args)
    except Exception as e:
        return f"[{name}: {e}]"

if __name__ == "__main__":
    print("📋 M-Light Function Table\n")
    tests = [
        ('$P', '"a,b,c",",",2'), ('$E', '"hello",2,4'),
        ('$A', '"A"'), ('$C', '65'), ('$L', '"hello"'),
        ('$F', '"hello","ell"'), ('$TR', '"hello","aeiou","-----"'),
    ]
    for n, a in tests:
        print(f"  {n}({a}) = {repr(eval_function(n, a))}")
