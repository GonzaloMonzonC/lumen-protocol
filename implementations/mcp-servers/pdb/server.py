import sys, json
try:
    with open(r'C:\Users\gonzalo\pdb_min_test.log', 'w') as f:
        f.write('alive\n')
except:
    pass

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
            send({"jsonrpc":"2.0","id":mid,"result":{"capabilities":{"tools":{}}}})
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
