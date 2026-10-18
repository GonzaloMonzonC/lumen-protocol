import sys, json, os
# Debug log removed for public repo

# Stick to ASCII to avoid any encoding issues
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pdb_tools import TOOLS, HANDLERS, tools_for_profile, resolve_profile
from lumen_mcp_stdio import read_message, write_message

# H6: dos perfiles. 'agente' por defecto (catálogo corto); 'admin' opt-in con
# --profile admin o LUMEN_PDB_PROFILE=admin. El admin no se activa solo.
PROFILE = resolve_profile(sys.argv)
EXPOSED = tools_for_profile(PROFILE)
_EXPOSED_NAMES = {t["name"] for t in EXPOSED}

while True:
    try:
        msg = read_message()
    except (EOFError, TimeoutError, ValueError, json.JSONDecodeError):
        break
    if msg is None:
        break
    mid = msg.get("id")
    method = msg.get("method", "")
    if method == "initialize":
        write_message({"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2025-03-26","capabilities":{"tools":{}},"serverInfo":{"name":"lumen-pdb","version":"1.0.0"}}})
    elif method == "ping":
        # Keepalive de Hermes: responder siempre, o el cliente lo da por muerto
        write_message({"jsonrpc":"2.0","id":mid,"result":{}})
    elif method == "notifications/initialized":
        pass  # notification: sin respuesta
    elif method == "tools/list":
        write_message({"jsonrpc":"2.0","id":mid,"result":{"tools":EXPOSED}})
    elif method == "tools/call":
        p = msg.get("params",{})
        nombre = p.get("name","")
        # H6: en perfil agente, una tool de admin existe en HANDLERS pero no se
        # sirve. El error lo dice y nombra la salida, en vez de "Unknown tool".
        if nombre not in _EXPOSED_NAMES:
            if nombre in HANDLERS:
                write_message({"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":(
                    f"Tool '{nombre}' existe pero no esta en el perfil '{PROFILE}'. "
                    f"Arranca el server con --profile admin o LUMEN_PDB_PROFILE=admin.")}})
            else:
                write_message({"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":f"Unknown tool: {nombre}"}})
            continue
        h = HANDLERS.get(nombre)
        if h:
            try:
                r = h(p.get("arguments",{}))
                write_message({"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text","text":json.dumps(r)}]}})
            except Exception as e:
                write_message({"jsonrpc":"2.0","id":mid,"error":{"code":-32603,"message":str(e)}})
    else:
        # Métodos desconocidos (p.ej. keepalives custom): responder -32601
        # SOLO si es un request (tiene id) — el cliente considera el server vivo.
        # Si es una NOTIFICACIÓN sin id (JSON-RPC), NO se responde (matiz del
        # protocolo: las notificaciones no reciben respuesta; responder con
        # id:null podría confundir al cliente).
        if mid is not None:
            write_message({"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":f"Unknown method: {method}"}})
