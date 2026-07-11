#!/usr/bin/env python3
"""
m_routines.py — ML-VM-03: Runtime Routines (DO ^script).

Inspirado en cómo MSM ejecutaba rutinas desde ^ROUTINE.

Características:
- Almacenar scripts en ^ROUTINE("name")
- Ejecutar vía DO name o DO ^name
- Paso de parámetros (args)
- Retorno de valores ($Q, QUIT)
- Integración con StackVM + Function Table
- Auto-detección: scripts en PDB o locales

Autor: Hermes + CadencesLab
Licencia: MIT
"""

import sys, os, json
from typing import Any, Optional

# ── Runtime Registry ──

_routines = {}  # cache local: name → code

def register(name: str, code: str):
    """Registrar script en el runtime local.
    
    MSM: S ^ROUTINE("name",line_no)=code_line
    PDB: register("name", "multi\\nline\\nscript")
    """
    _routines[name.upper()] = code

def load_from_pdb(name: str) -> Optional[str]:
    """Cargar script desde ^ROUTINE en PDB.
    
    MSM: G @entry^routine
    PDB: lee de ^ROUTINE("name",n) y reconstruye
    """
    try:
        sp = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
        if sp not in sys.path: sys.path.insert(0, sp)
        from pdb_tools import tool_order, tool_get
        
        lines = []
        key = ""
        while True:
            r = tool_order({"ns": "ROUTINE", "subs": [key], "direction": 1})
            if not r.get("success") or r.get("value") is None:
                break
            key = r["value"]
            r2 = tool_get({"ns": "ROUTINE", "subs": [name, key]})
            if r2.get("success") and r2.get("value") is not None:
                lines.append(str(r2["value"]))
        
        if lines:
            code = "\n".join(lines)
            register(name, code)
            return code
    except:
        pass
    return None

def get_routine(name: str) -> Optional[str]:
    """Obtener script por nombre.
    
    Busca en: 1) cache local, 2) ^ROUTINE en PDB, 3) archivo
    """
    name = name.upper()
    
    # Cache local
    if name in _routines:
        return _routines[name]
    
    # ^ROUTINE en PDB
    code = load_from_pdb(name)
    if code:
        return code
    
    # Archivo .m en rutas conocidas
    for path in [f"{name}.m", f"{name.lower()}.m", f"routines/{name}.m"]:
        if os.path.exists(path):
            with open(path) as f:
                code = f.read()
                register(name, code)
                return code
    
    return None

def list_routines() -> list:
    """Listar rutinas disponibles."""
    names = list(_routines.keys())
    try:
        sp = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
        if sp not in sys.path: sys.path.insert(0, sp)
        from pdb_tools import tool_order
        key = ""
        while True:
            r = tool_order({"ns": "ROUTINE", "subs": [key], "direction": 1})
            if not r.get("success") or r.get("value") is None:
                break
            key = r["value"]
            if key not in names:
                names.append(key)
    except:
        pass
    return sorted(names)


# ── Executor ──

class RoutineExecutor:
    """Ejecutor de rutinas con paso de parámetros.
    
    MSM: DO ^routine(args) → JOB + parámetros.
    PDB: exec("routine", args) → resultado.
    """
    
    def __init__(self, vm_class=None):
        self.vm_class = vm_class
        self._import_vm()
    
    def _import_vm(self):
        if self.vm_class is None:
            try:
                sp = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync")
                if sp not in sys.path: sys.path.insert(0, sp)
                from m_stackvm import StackVM
                self.vm_class = StackVM
            except:
                pass
    
    def exec(self, name: str, args: list = None, vars_in: dict = None) -> dict:
        """Ejecutar rutina DO ^name(args).
        
        MSM: D ^routine(args) → JOB routine + parámetros.
        PDB: exec("routine", [arg1, arg2]) → resultado.
        
        Args:
            name: nombre de la rutina
            args: lista de argumentos ($1, $2, ...)
            vars_in: variables predefinidas
        
        Returns: {"result": ..., "vars": ..., "error": ...}
        """
        code = get_routine(name)
        if not code:
            return {"error": f"Routine {name} not found"}
        
        if not self.vm_class:
            return {"error": "StackVM not available"}
        
        vm = self.vm_class()
        
        # Pasar argumentos como variables $1, $2, ...
        if args:
            for i, arg in enumerate(args, 1):
                vm.vars[f"${i}"] = arg
            vm.vars["$ZARGS"] = len(args)
        
        # Variables predefinidas
        if vars_in:
            vm.vars.update(vars_in)
        
        # Compilar todo el script de una vez
        vm.compile(code)
        try:
            result = vm.exec()
            result["routine"] = name
            result["args"] = args
            return result
            
        except Exception as e:
            return {"error": str(e), "routine": name, "args": args}
    
    def do(self, ref: str, vm_host=None) -> Any:
        """DO ref — ejecutar desde el StackVM.
        
        ref: "^routine" o "^routine(args)"
        """
        ref = ref.strip()
        args = None
        
        # Parsear ^routine(args)
        if '(' in ref:
            name = ref[1:ref.index('(')]
            args_str = ref[ref.index('(')+1:ref.rindex(')')]
            args = [a.strip().strip('"') for a in args_str.split(',') if a.strip()]
        else:
            name = ref[1:] if ref.startswith('^') else ref
        
        vars_in = vm_host.vars if vm_host else None
        result = self.exec(name, args, vars_in)
        
        if result.get("result") is not None:
            return result["result"]
        if result.get("error"):
            raise RuntimeError(result["error"])
        return None


# ── Integración con StackVM ──

def patch_stackvm():
    """Añadir DO ^routine al StackVM."""
    try:
        sp = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync")
        if sp not in sys.path: sys.path.insert(0, sp)
        from m_stackvm import StackVM, OP_DO
        
        # Monkey-patch _exec_do
        original_do = StackVM._exec_do
        
        def _exec_do_patched(self, rest, inst=None):
            rest = rest.strip()
            if rest.startswith('^'):
                executor = RoutineExecutor()
                result = executor.do(rest, self)
                self.ops.append(result)
                return result
            elif original_do:
                return original_do(self, rest, inst)
        
        StackVM._exec_do = _exec_do_patched
        return True
    except:
        return False


# ── CLI ──

    def _save_bc(self, name, key, instrs):
        '''Guardar bytecode compilado en ^ROUTINE(name,key).'''
        try:
            from pdb_tools import tool_set, tool_kill
            tool_kill({"ns": "ROUTINE", "subs": [name, key]})
            for idx, inst in enumerate(instrs):
                tool_set({"ns": "ROUTINE", "subs": [name, key, str(idx)],
                         "value": f"{inst.opcode}|{inst.args}"})
            return True
        except: return False

    def _load_bc(self, name, key):
        '''Cargar bytecode cacheado desde ^ROUTINE.'''
        try:
            from pdb_tools import tool_order, tool_get
            from m_stackvm import StackOp
            instrs = []
            idx = ""
            while True:
                r = tool_order({"ns": "ROUTINE", "subs": [name, key, idx], "direction": 1})
                if not r.get("success") or r.get("value") is None: break
                idx = r["value"]
                r2 = tool_get({"ns": "ROUTINE", "subs": [name, key, idx]})
                if r2.get("success") and r2.get("value"):
                    parts = str(r2["value"]).split("|", 1)
                    if len(parts) == 2:
                        import ast
                        instrs.append(StackOp(parts[0], ast.literal_eval(parts[1])))
            return instrs if instrs else None
        except: return None

if __name__ == "__main__":
    import sys
    
    # Registrar rutina de ejemplo
    register("HELLO", """W "Hello from M-Light!"
S x=42
W x""")
    
    register("ECHO", """W "Args: ",$1
I $2>0 W " Arg2: ",$2""")
    
    cmd = sys.argv[1] if len(sys.argv) > 1 else "demo"
    
    if cmd == "demo":
        print("📋 M-Light Runtime Routines\n")
        
        # Ejecutar HELLO
        print("=== DO ^HELLO ===")
        executor = RoutineExecutor()
        result = executor.exec("HELLO")
        print(f"Result: {result}")
        
        print("\n=== DO ^ECHO(hello,42) ===")
        result2 = executor.exec("ECHO", ["hello", 42])
        print(f"Result: {result2}")
        
        print(f"\nRoutines: {list_routines()}")
    
    elif cmd == "run":
        name = sys.argv[2]
        args = sys.argv[3:] if len(sys.argv) > 3 else []
        executor = RoutineExecutor()
        result = executor.exec(name, args)
        print(f"DO ^{name}({','.join(str(a) for a in args)})")
        print(f"Result: {result}")
