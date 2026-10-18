#!/usr/bin/env python3
"""test_session_id_declarado_en_schemas.py — H3

Regla de CI: toda tool cuyo handler lea `session_id` debe declararlo en su
inputSchema. Sin esto, el aislamiento multi-agente existe en el servidor pero
es invisible para el cliente (39 tools en el censo del 18-oct-2026).

Sin dependencias, sin arrancar el server, sin PDB. Solo AST + imports de schemas.

Uso:
    python test_session_id_declarado_en_schemas.py [--repo <ruta>]
Salida: exit 0 si pasa, 1 si no.
"""
import argparse
import ast
import importlib
import sys
from pathlib import Path

MODULOS_SCHEMA = {
    "FILE_TOOL_SCHEMAS": "file_tools",
    "PDB_WATCH_SCHEMAS": "pdb_watch",
    "FUZZY_SEARCH_SCHEMAS": "fuzzy_search",
    "OBJECTIVE_SCHEMAS": "objective_loop",
    "KANBAN_SCHEMAS": "kanban",
    "PDB_NS_SCHEMAS": "pdb_ns",
}


def find_thinking_repo(arg):
    if arg:
        p = Path(arg)
        return p / "implementations/mcp-servers/thinking" if (p / "implementations").is_dir() else p
    for parent in Path(__file__).resolve().parents:
        cand = parent / "implementations/mcp-servers/thinking"
        if cand.is_dir():
            return cand
    return Path.home() / "Documents/GitHub/lumen-protocol/implementations/mcp-servers/thinking"


def flatten_tools(node, saltados):
    """Resuelve [..] + [..] + VAR + ... -> (dicts literales, nombres de var externos)."""
    out, externos = [], []

    def rec(n):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            rec(n.left); rec(n.right)
        elif isinstance(n, ast.List):
            for e in n.elts:
                try:
                    v = ast.literal_eval(e)
                    if isinstance(v, dict):
                        out.append(v)
                    else:
                        saltados.append(type(v).__name__)
                except Exception:
                    saltados.append(ast.dump(e)[:60])
        elif isinstance(n, ast.Name):
            externos.append(n.id)
        else:
            saltados.append(ast.dump(n)[:60])

    rec(node)
    return out, externos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    think = find_thinking_repo(args.repo)
    server = think / "server.py"
    if not server.is_file():
        print(f"SKIP: no encuentro {server}")
        return 0            # en CI sin repo: no fallar

    src = server.read_text(encoding="utf-8")
    tree = ast.parse(src)

    asign = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    asign[t.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                asign[node.target.id] = node.value

    if "TOOLS" not in asign or "HANDLERS" not in asign:
        print(f"SKIP: {server} no expone TOOLS/HANDLERS de primer nivel")
        return 0

    saltados = []
    propias, externas = flatten_tools(asign["TOOLS"], saltados)

    # schemas de los modulos externos
    sys.path.insert(0, str(think))
    todas = list(propias)
    for var in externas:
        if var not in MODULOS_SCHEMA:
            print(f"AVISO: VAR desconocida en TOOLS: {var}")
            continue
        try:
            mod = importlib.import_module(MODULOS_SCHEMA[var])
            todas.extend(getattr(mod, var))
        except Exception as e:
            print(f"AVISO: no pude importar {var}: {e}")

    # handlers con su funcion (y desde que fichero)
    handlers, origen = {}, {}
    for k, v in zip(asign["HANDLERS"].keys, asign["HANDLERS"].values):
        if isinstance(k, ast.Constant) and isinstance(v, ast.Name):
            handlers[k.value] = v.id
            origen[k.value] = server

    # los handlers de modulos externos: los buscamos por import
    cuerpos = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    externos_fn = {}
    for var, modname in MODULOS_SCHEMA.items():
        try:
            mod = importlib.import_module(modname)
            import inspect
            for fn in vars(mod).values():
                if inspect.isfunction(fn) and fn.__module__ == modname:
                    externos_fn[fn.__name__] = inspect.getsource(fn)
        except Exception:
            pass

    def lee_session_id(fn_name):
        n = cuerpos.get(fn_name)
        if n is not None:
            for sub in ast.walk(n):
                if isinstance(sub, ast.arg) and sub.arg == "session_id":
                    return True
                if isinstance(sub, ast.Constant) and sub.value == "session_id":
                    return True
                if isinstance(sub, ast.Name) and sub.id == "session_id":
                    return True
            return False
        src_ext = externos_fn.get(fn_name)
        if src_ext:
            return "session_id" in src_ext
        return False

    # tools cuyo handler esta en un modulo externo: buscarlo por nombre de tool
    # (objective_loop.map: TOOL_HANDLERS o HANDLERS en el modulo)
    for modname in MODULOS_SCHEMA.values():
        try:
            mod = importlib.import_module(modname)
            for dictname in ("HANDLERS", "TOOL_HANDLERS"):
                d = getattr(mod, dictname, None)
                if isinstance(d, dict):
                    for tk, fn in d.items():
                        if callable(fn) and tk not in handlers:
                            handlers[tk] = fn.__name__
        except Exception:
            pass

    con_prop, sin_prop, sin_handler, descuadre = [], [], [], []
    for t in todas:
        name = t.get("name")
        if not name:
            continue
        props = (t.get("inputSchema") or {}).get("properties") or {}
        declara = "session_id" in props
        fn = handlers.get(name)
        if fn is None:
            sin_handler.append(name)
            continue
        lee = lee_session_id(fn)
        if declara and not lee:
            descuadre.append((name, fn))     # declara pero no usa: informativo
        if lee and declara:
            con_prop.append(name)
        elif lee and not declara:
            sin_prop.append((name, fn))

    print(f"TOOLS totales            : {len(todas)}")
    print(f"  propias server.py      : {len(propias)}")
    print(f"  de modulos externos    : {len(todas) - len(propias)}")
    print(f"handlers resueltos       : {len(handlers)}")
    print(f"leen session_id y lo declaran : {len(con_prop)}")
    print(f"leen session_id y NO declaran : {len(sin_prop)}")
    print(f"declaran pero no lo leen      : {len(descuadre)}")
    print(f"tools sin handler localizable : {len(sin_handler)}")
    if saltados:
        print(f"entradas de TOOLS no resueltas: {len(saltados)} -> {saltados[:4]}")

    if args.verbose or sin_prop:
        print("\n=== LEEN session_id Y NO LO DECLARAN ===")
        for n, fn in sin_prop:
            print(f"  {n:30s} ({fn})")

    if sin_prop:
        print(f"\nFALLO: {len(sin_prop)} tool(s) honran session_id y no lo declaran.")
        print("Anade la propiedad al inputSchema (el handler ya la lee: no hay cambio de comportamiento).")
        return 1

    print("\nOK: toda tool que lee session_id lo declara en su schema.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
