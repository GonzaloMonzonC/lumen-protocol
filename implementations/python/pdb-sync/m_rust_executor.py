#!/usr/bin/env python3
"""
m_rust_executor.py — Rust M-Light executor (reemplazo de StackVM para VM-API).

Reemplaza m_routines.RoutineExecutor usando lumen_mlight.execute()
en vez de Python StackVM. Compilación 17μs, $O BTreeMap, $H cacheado.
"""
import sys, os, json
import _paths
from typing import Any, Optional

PDB_DIR = _paths.PDB_DIR_S
if PDB_DIR not in sys.path:
    sys.path.insert(0, PDB_DIR)

from lumen_mlight import execute_sqlite

_routines = {}  # cache local: name → code

def register(name: str, code: str):
    """Registrar script en runtime local (misma API que m_routines)."""
    _routines[name] = code
    from m_routines import register as py_register
    py_register(name, code)

def get_routine(name: str) -> Optional[str]:
    """Obtener código de rutina desde cache local o PDB."""
    if name in _routines:
        return _routines[name]
    from m_routines import get_routine as py_get
    return py_get(name)

def available() -> bool:
    """Verificar que el DLL de Rust está disponible."""
    try:
        from lumen_mlight import ensure_built
        return ensure_built(quiet=True)
    except Exception:
        return False


class RustExecutor:
    """Ejecutor de rutinas M usando Rust M-Light.

    Misma interfaz que RoutineExecutor pero backend nativo.
    """

    def exec(self, name: str, args: list = None, vars_in: dict = None) -> dict:
        """Ejecutar rutina DO ^name(args) via Rust MVM.

        Args:
            name: nombre de rutina (ej: "UTILS") o "label^ROUTINE"
            args: lista de argumentos ($1, $2, ...)
            vars_in: variables predefinidas

        Returns:
            dict con {"result": ..., "vars": ..., "error": ...}
        """
        code = get_routine(name)
        if not code:
            return {"error": f"Routine {name} not found"}

        # Armar source: call label con args
        # Si name es "label^ROUTINE", extraer label y routine
        if "^" in name:
            label, routine = name.split("^", 1)
        else:
            label = name
            routine = name

        # Construir source que ejecute la rutina
        if args:
            # Pasar args como valores directamente
            arg_str = ','.join(str(json.dumps(a)) for a in args)
            source = f"D {label}^{routine}({arg_str})"
        else:
            source = f"D {label}^{routine}"

        # Preparar vars
        vars_dict = {}
        if args:
            for i, arg in enumerate(args, 1):
                vars_dict[f"${i}"] = arg
            vars_dict["$ZARGS"] = len(args)
        if vars_in:
            vars_dict.update(vars_in)

        try:
            response = execute_sqlite(
                source=source,
                routines={routine: code},
                variables=vars_dict,
                gas_limit=100000,
                sqlite_path=_paths.DB_PATH,
            )

            # Extraer resultado
            state = response.get("state", {})
            error = state.get("error", {}).get("zerror")
            
            # Resultado = último valor en el stack (QUIT)
            stack = state.get("stack", [])
            result = stack[-1] if stack else None

            return {
                "result": result,
                "vars": {},
                "error": error,
                "_routine": name,
                "_args": args,
                "_rust": True,
            }

        except Exception as e:
            return {"error": str(e), "_routine": name, "_args": args, "_rust": True}

    def exec_code(self, source: str, args: list = None, vars_in: dict = None) -> dict:
        """Ejecutar código M inline via Rust MVM."""
        try:
            # Preparar vars: args → $1..$n + $ZARGS (mismo contrato que exec)
            vars_dict = {}
            if args:
                for i, arg in enumerate(args, 1):
                    vars_dict[f"${i}"] = arg
                vars_dict["$ZARGS"] = len(args)
            if vars_in:
                vars_dict.update(vars_in)

            response = execute_sqlite(
                source=source,
                variables=vars_dict,
                gas_limit=100000,
                sqlite_path=_paths.DB_PATH,
            )
            state = response.get("state", {})
            error = state.get("error", {}).get("zerror")

            # Resultado = último valor en el stack (QUIT), como en exec()
            stack = state.get("stack", [])
            result = stack[-1] if stack else None

            return {
                "result": result,
                "vars": {},
                "error": error,
                "_rust": True,
            }
        except Exception as e:
            return {"error": str(e), "_rust": True}

    def do(self, ref: str, vm_host=None) -> Any:
        """DO ref via Rust MVM."""
        ref = ref.strip()
        args = None

        if '(' in ref:
            name = ref[1:ref.index('(')] if ref.startswith('^') else ref
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
