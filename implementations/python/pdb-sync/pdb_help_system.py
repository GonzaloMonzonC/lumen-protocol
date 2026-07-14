#!/usr/bin/env python3
"""
pdb_help_system.py — Sistema de ayuda jerárquico (^%HELP adaptado).

Para agentes: cualquier agente consulta ayuda contextual en ^System("help").

Inspirado en ^%HELP (612 líneas) de MSM:
  ^%HELP(0, "LIBRARY", 1) = lista de utilidades
  ^%HELP(0, "LIBRARY", "GLOBAL UTILITIES", 1) = %FGR~%FGS~%GCH...

Nuestro: ^System("help", category, subcategory, ...) = texto

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os
import _paths  # rutas repo-relativas
from datetime import datetime, timezone

def _get_tools():
    pdb_dir = _paths.PDB_DIR_S
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order
    return tool_set, tool_get, tool_order

HELP_DATA = {
    # ── Top-level categories ──
    "pdb": {"title": "PDB Lumen", "desc": "Operaciones con la base de datos jerárquica"},
    "m-light": {"title": "M-Light", "desc": "Lenguaje MUMPS para agentes"},
    "agents": {"title": "Agentes", "desc": "Gestión de agentes del ecosistema"},
    "ddp": {"title": "DDP", "desc": "Protocolo de datos distribuido"},
    "journal": {"title": "Journaling", "desc": "Sistema de journaling y recovery"},
    
    # ── PDB ──
    "pdb:set": {"title": "SET", "desc": "Escribir un valor en ^namespace(subs)"},
    "pdb:get": {"title": "GET / $GET", "desc": "Leer un valor de ^namespace(subs)"},
    "pdb:order": {"title": "ORDER / $ORDER / $O", "desc": "Iterar subíndices jerárquicamente"},
    "pdb:kill": {"title": "KILL", "desc": "Eliminar un nodo o subárbol"},
    "pdb:data": {"title": "DATA / $DATA / $D", "desc": "Verificar existencia de un nodo"},
    "pdb:query": {"title": "SQL Query", "desc": "Consultas SQL sobre los datos"},
    
    # ── M-Light ──
    "m-light:get": {"title": "$GET multi-nivel", "desc": "Leer valor en ^ns(s1, s2, ...)"},
    "m-light:order": {"title": "$ORDER", "desc": "S el alma de MUMPS"},
    "m-light:for": {"title": "FOR loop", "desc": "F i=1:1:N... iteración"},
    "m-light:if": {"title": "IF / I", "desc": "Condicional"},
    "m-light:set": {"title": "SET / S", "desc": "Asignación de variables"},
    "m-light:write": {"title": "WRITE / W", "desc": "Salida de texto"},
    
    # ── Agentes ──
    "agents:hermes": {"title": "Hermes", "desc": "Agente principal. Build + orquestación"},
    "agents:zalo": {"title": "Zalo", "desc": "Knowledge Base. Qwen 32B. Validación"},
    "agents:lisa": {"title": "Lisa", "desc": "Orquestadora. DeepSeek Pro. Estrategia"},
    "agents:tom": {"title": "Tom", "desc": "Worker. Granite/GLM. Procesamiento rápido"},
    "agents:angi": {"title": "Angi", "desc": "PM. Dashboard 3D. Tracking de sprints"},
    
    # ── DDP ──
    "ddp:links": {"title": "Links", "desc": "Conexiones entre agentes (service bindings)"},
    "ddp:circuits": {"title": "Circuits", "desc": "Canales lógicos de comunicación"},
    "ddp:nodes": {"title": "Nodes", "desc": "Agentes registrados en la red DDP"},
    "ddp:messages": {"title": "Messages", "desc": "Mensajes entre agentes vía DDP"},
    
    # ── Journal ──
    "journal:changes": {"title": "^CHANGES", "desc": "Registro de todas las operaciones"},
    "journal:control": {"title": "Control Block", "desc": "Métricas y estado del journal"},
    "journal:recovery": {"title": "VERIFY Recovery", "desc": "3 checks de integridad"},
    "journal:bij": {"title": "BIJ", "desc": "Before-Image Journal para rollback"},
}

# ── API ──

def help_init():
    """Cargar ayuda en ^System("help")."""
    tool_set, _, _ = _get_tools()
    for path, info in HELP_DATA.items():
        parts = path.split(":")
        subs = ["data"] + parts
        tool_set({"ns": "System", "subs": subs, "value": info})
    tool_set({"ns": "System", "subs": ["help", "_meta"], "value": {
        "entries": len(HELP_DATA),
        "categories": len(set(p.split(":")[0] for p in HELP_DATA)),
        "initialized": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }})
    return len(HELP_DATA)

def help_get(topic):
    """Obtener ayuda de un tópico vía SQL directo."""
    import sqlite3, os, json
    pdb_path = _paths.DB_PATH
    db = sqlite3.connect(f"file:{pdb_path}?mode=ro", uri=True)
    from pdb_tools import encode_subkey, _decode_value
    parts = topic.split(":")
    sk = encode_subkey(["help", "data"] + parts)
    row = db.execute("SELECT value FROM _globals WHERE ns='System' AND subkey=?", (sk,)).fetchone()
    db.close()
    if row:
        return _decode_value(row[0])
    return None

def help_categories():
    """Listar categorías vía SQL directo."""
    import sqlite3, os
    pdb_path = _paths.DB_PATH
    db = sqlite3.connect(f"file:{pdb_path}?mode=ro", uri=True)
    from pdb_tools import encode_subkey, decode_subkey
    prefix = encode_subkey(["help", "data"])
    rows = db.execute(
        "SELECT DISTINCT substr(subkey, ?, ?) FROM _globals WHERE ns='System' AND subkey LIKE ?",
        (len(prefix) + 1, 100, prefix.hex() + '%')
    ).fetchall()
    db.close()
    cats = set()
    for (partial,) in rows:
        try:
            key_bytes = bytes.fromhex(partial)
            for ch in key_bytes.split(b'\xff'):
                if ch and ch[0:1] == b'\x02':
                    cats.add(ch[1:].decode('utf-8', errors='replace'))
        except: pass
    return list(cats)

def help_format(topic):
    """Formatear ayuda para output."""
    info = help_get(topic)
    if not info:
        return f"No help for '{topic}'"
    return f"{info['title']}: {info['desc']}"

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "init"
    if cmd == "init":
        n = help_init()
        print(f"✅ Help: {n} entries loaded to ^System(\"help\")")
    elif cmd == "get":
        topic = sys.argv[2]
        print(help_format(topic))
    elif cmd == "categories":
        for c in help_categories():
            print(f"  {c}")
