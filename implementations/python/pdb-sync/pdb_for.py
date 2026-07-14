#!/usr/bin/env python3
"""
pdb_for.py — MSM-07: FOR iteración nativa B-tree.

Inspirado en MSM B-tree opcode 'f' (case 0x66 en FUN_48c010).

Stateful iterator: establece contexto, itera con límites.
Extiende tool_order con:
- Iteración por rango (start..end)
- Pattern matching durante iteración
- Callback por nodo
- Stateful cursor

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os
import _paths  # rutas repo-relativas

def _get_tools():
    pdb_dir = _paths.PDB_DIR_S
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_get, tool_order, tool_data, tool_set
    return tool_get, tool_order, tool_data, tool_set

# ── Stateful Iterator ───────────────────────────────────────────

class PDBFor:
    """Iterador stateful sobre namespaces PDB.
    
    Uso:
        f = PDBFor("System")
        for key in f:
            print(key, f.value)
    """
    
    def __init__(self, ns, subs_start=None, subs_end=None, direction=1, pattern=None):
        self.ns = ns
        self.subs_start = subs_start or []
        self.subs_end = subs_end
        self.direction = direction  # 1 = forward, -1 = backward
        self.pattern = pattern
        self._current = None
        self._value = None
        self._done = False
        self._buf = None  # MSM: strncpy buffer
        self._init_context()
    
    def _init_context(self):
        """Establecer contexto de iteración (MSM: flag |= 8 + strncpy)."""
        tg, to, td, ts = _get_tools()
        subs = self.subs_start[:]
        subs.append("")
        r = to({"ns": self.ns, "subs": subs, "direction": self.direction})
        self._buf = self.subs_start[:]
        if r.get("success") and r.get("value") is not None:
            self._current = r["value"]
            r2 = tg({"ns": self.ns, "subs": self.subs_start + [self._current]})
            self._value = r2.get("value") if r2.get("success") else None
        else:
            self._done = True
    
    def __iter__(self):
        return self
    
    def __next__(self):
        if self._done or self._current is None:
            raise StopIteration
        result = self._current
        # Avanzar
        tg, to, td, ts = _get_tools()
        subs = self.subs_start[:]
        subs.append(self._current)
        r = to({"ns": self.ns, "subs": subs, "direction": self.direction})
        if r.get("success") and r.get("value") is not None:
            self._current = r["value"]
            r2 = tg({"ns": self.ns, "subs": self.subs_start + [self._current]})
            self._value = r2.get("value") if r2.get("success") else None
        else:
            self._done = True
            self._current = None
            self._value = None
        return result
    
    @property
    def value(self):
        return self._value
    
    @property
    def current(self):
        return self._current
    
    def reset(self):
        """Reiniciar iterador (MSM: reset flag)."""
        self._done = False
        self._init_context()
    
    def skip(self, n=1):
        """Saltar N elementos (MSM: step parameter)."""
        for _ in range(n):
            try: self.__next__()
            except StopIteration: break

# ── Functional API ──────────────────────────────────────────────

def tool_for(ns, subs_start=None, subs_end=None, direction=1, callback=None):
    """Iterar sobre subíndices con callback.
    
    MSM: FOR key = iterar con límites y paso.
    Nosotros: callback recibe (key, value, index) → True para continuar.
    
    Returns: lista de (key, value) si no hay callback, o None.
    """
    results = []
    f = PDBFor(ns, subs_start, subs_end, direction)
    idx = 0
    for key in f:
        if callback:
            if not callback(key, f.value, idx):
                break
        else:
            results.append((key, f.value))
        idx += 1
    return results if not callback else None

def tool_for_range(ns, start_pattern, end_pattern, direction=1):
    """Iterar entre dos patrones.
    
    MSM: FOR x = start:step:end
    """
    results = []
    f = PDBFor(ns, start_pattern, end_pattern, direction)
    for key in f:
        if end_pattern and key > end_pattern:
            break
        results.append((key, f.value))
    return results

# ── CLI ──

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "demo"
    
    if cmd == "demo":
        print("📋 PDB FOR — Stateful Iterator Demo")
        print()
        
        # System namespace
        f = PDBFor("System")
        print("System namespace keys:")
        for i, key in enumerate(f):
            print(f"  {i}: {key} = {str(f.value)[:60]}")
            if i >= 10: break
        
        print()
        print("With callback:")
        tool_for("System", callback=lambda k, v, i: print(f"  [{i}] {k}") or i < 5)
    
    elif cmd == "range":
        ns = sys.argv[2] if len(sys.argv) > 2 else "System"
        start = sys.argv[3] if len(sys.argv) > 3 else ""
        end = sys.argv[4] if len(sys.argv) > 4 else None
        results = tool_for_range(ns, [start], [end] if end else None)
        for k, v in results[:20]:
            print(f"  {k} = {str(v)[:60]}")
