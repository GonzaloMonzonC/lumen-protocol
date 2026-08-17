import sys, json, os
# Debug log removed for public repo

# Stick to ASCII to avoid any encoding issues
from pdb_tools import TOOLS, HANDLERS

def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()

while True:
    line = sys.stdin.readline()
    if not line:
        break
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
        mid = msg.get("id")
        method = msg.get("method", "")
        if method == "initialize":
            send({"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2025-03-26","capabilities":{"tools":{}},"serverInfo":{"name":"lumen-pdb","version":"1.0.0"}}})
        elif method == "tools/list":
            send({"jsonrpc":"2.0","id":mid,"result":{"tools":TOOLS}})
        elif method == "tools/call":
            p = msg.get("params",{})
            h = HANDLERS.get(p.get("name",""))
            if h:
                try:
                    r = h(p.get("arguments",{}))
                    send({"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text","text":json.dumps(r)}]}})
                except Exception as e:
                    send({"jsonrpc":"2.0","id":mid,"error":{"code":-32603,"message":str(e)}})
    except Exception:
        pass
