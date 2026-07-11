#!/usr/bin/env python3
"""
pdb_indirect.py — MSM-08: ^ (INDIRECT) Referencias dinámicas.

Inspirado en MSM B-tree opcode '^' (case 0x5e en FUN_48c010).
Permite resolver referencias dinámicas tipo ^ns("sub1","sub2").

MSM: flag |= 0x20 + modo indirección → evaluar string como ref.
PDB: pdb_resolve("^System(config,param)") → value

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, re

def _get_tools():
    pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_get, tool_set, tool_kill, tool_order, tool_data
    return tool_get, tool_set, tool_kill, tool_order, tool_data

# ── Resolver ────────────────────────────────────────────────────

def tool_resolve(ref_string):
    """Resolver referencia dinámica.
    
    MSM: '^' opcode → flag |= 0x20, modo indirecto.
    PDB: pdb_resolve("^System(config)") → valor.
    
    Formato: ^Namespace(sub1,sub2,...,subN)
    """
    tg, ts, tk, to, td = _get_tools()
    
    m = re.match(r'\^(\w+)\(([^)]*)\)', ref_string)
    if not m:
        return {"success": False, "error": "Invalid reference format"}
    
    ns = m.group(1)
    subs_str = m.group(2)
    
    # Parse subscripts
    subs = []
    if subs_str.strip():
        for part in re.findall(r'"([^"]*)"|\'([^\']*)\'|([^,]+)', subs_str):
            s = part[0] or part[1] or part[2]
            subs.append(s.strip().strip('"').strip("'"))
    
    return tool_resolve_ns(ns, subs)

def tool_resolve_ns(ns, subs):
    """Resolver ^ns(subs) → valor."""
    tg, ts, tk, to, td = _get_tools()
    
    # $DATA
    r = td({"ns": ns, "subs": subs})
    data_type = r.get("value", 0) if r.get("success") else 0
    
    result = {
        "ns": ns,
        "subs": subs,
        "data_type": data_type,  # 0=no existe, 1=sin hijos, 10=con hijos, 11=ambos
    }
    
    if data_type in (1, 11):
        r2 = tg({"ns": ns, "subs": subs})
        result["value"] = r2.get("value") if r2.get("success") else None
    
    if data_type in (10, 11):
        # Tiene hijos — listar primeros
        r3 = to({"ns": ns, "subs": subs + [""], "direction": 1})
        if r3.get("success") and r3.get("value") is not None:
            result["first_child"] = r3["value"]
    
    return result

# ── Indirection context (MSM: flag |= 0x20) ─────────────────────

class IndirectContext:
    """Contexto de indirección (como MSM flag 0x20).
    
    Mantiene una referencia actual para operaciones sucesivas.
    """
    
    def __init__(self):
        self.ns = None
        self.subs = []
        self.flag = 0
    
    def set_ref(self, ref_string):
        """Establecer referencia actual."""
        r = tool_resolve(ref_string)
        if r.get("ns"):
            self.ns = r["ns"]
            self.subs = r["subs"]
            self.flag |= 0x20  # MSM: indirect mode
        return r
    
    def get(self):
        """Obtener valor en la referencia actual."""
        if not self.ns: return None
        return tool_resolve_ns(self.ns, self.subs)
    
    def set(self, value):
        """Establecer valor en la referencia actual."""
        if not self.ns: return None
        ts, _, _, _, _ = _get_tools()
        ts({"ns": self.ns, "subs": self.subs, "value": value})
        return True

# ── CLI ──

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "demo"
    
    if cmd == "demo":
        print("📋 PDB INDIRECT — Dynamic References (^)")
        print()
        
        # Resolver ^System(config)
        r = tool_resolve("^System(config)")
        print(f"  ^System(config) = {r}")
        print()
        
        # Contexto indirecto
        ctx = IndirectContext()
        r = ctx.set_ref("^System(help)")
        print(f"  Context ref: {r}")
        print(f"  Context get: {ctx.get()}")
