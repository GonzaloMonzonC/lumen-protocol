import sys, json, os
# Debug log removed for public repo

# Stick to ASCII to avoid any encoding issues
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pdb_tools import TOOLS, HANDLERS
from lumen_mcp_stdio import read_message, write_message

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
        write_message({"jsonrpc":"2.0","id":mid,"result":{"tools":TOOLS}})
    elif method == "tools/call":
        p = msg.get("params",{})
        h = HANDLERS.get(p.get("name",""))
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
