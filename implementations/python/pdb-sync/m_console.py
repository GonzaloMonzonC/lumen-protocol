#!/usr/bin/env python3
"""M-Light Console — single-file terminal con WebSocket + HTTP."""
import sys, os, json, time, asyncio, threading
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync"))
from m_stackvm import StackVM
from pdb_tools import tool_order, tool_get

# ── HTML (embedded) ──
PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>M-Light</title>
<style>*{margin:0;padding:0;box-sizing:border-box}
body{background:#1e1e1e;color:#d4d4d4;font-family:'Cascadia Code','Consolas',monospace;height:100vh;display:flex;flex-direction:column}
#h{background:#2d2d2d;padding:6px 14px;border-bottom:1px solid #404040;font-size:13px;flex-shrink:0;display:flex;gap:10px}
#h .t{color:#569cd6;font-weight:600}#h .s{color:#6a9955;font-size:11px;margin-left:auto}
#term{flex:1;overflow-y:auto;padding:8px 14px;font-size:14px;line-height:1.5}
#l{display:flex;padding:4px 14px 10px;flex-shrink:0}
#p{color:#569cd6;margin-right:6px;font-size:14px;padding-top:2px}
#i{flex:1;background:#2d2d2d;border:1px solid #404040;color:#d4d4d4;font-family:inherit;font-size:14px;padding:4px 8px;border-radius:3px;outline:none}
#i:focus{border-color:#569cd6}.o{color:#d4d4d4}.n{color:#6a9955}.e{color:#f44747}.a{color:#ce9178}
</style></head><body>
<div id=h><span class=t>⬡ M-Light</span><span style=color:#6a9955>v2</span><span class=s id=s>⏳</span></div>
<div id=term><div class=n>⬡ M-Light v2 — type M or /ai</div><div id=m></div></div>
<div id=l><span id=p>❯</span><input id=i autofocus spellcheck=false></div>
<script>
const term=document.getElementById('term'),i=document.getElementById('i'),s=document.getElementById('s'),m=document.getElementById('m');
let ws;let port=location.port||'80';
function connect(){ws=new WebSocket('ws://'+location.hostname+':'+port+'/ws');ws.onopen=()=>{s.textContent='●';s.style.color='#6a9955'};ws.onclose=()=>{s.textContent='○';s.style.color='#f44747';setTimeout(connect,2000)};ws.onmessage=e=>{let d=JSON.parse(e.data);let x=document.createElement('div');x.className=d.type=='error'?'e':d.type=='ai'?'a':'n';x.textContent=d.text;m.appendChild(x);term.scrollTop=term.scrollHeight}}
i.addEventListener('keydown',e=>{if(e.key==='Enter'&&i.value.trim()){let l=i.value;let x=document.createElement('div');x.className='o';x.textContent='❯ '+l;m.appendChild(x);ws.send(JSON.stringify({type:'cmd',line:l}));i.value=''}})
connect();
</script></body></html>"""

# ── Commands ──
def cmd_help():
    return "S x=42 | W x | D ^ROUTINE | F i=1:1:10 | ZW ^NS | ZR | ZJOB | D ^%SS | /ai prompt | /help"

def cmd_ss():
    from pdb_ddp_client import DDPClient
    st = DDPClient().status()
    return f"System: {st.get('entries','?')} entries | Lag: {st.get('lag_ms',0)}ms"

def cmd_zw(ns):
    try:
        keys = []; k = ""
        for _ in range(50):
            r = tool_order({"ns": ns, "subs": [k], "direction": 1})
            if not r.get("success") or not r.get("value"): break
            k = r["value"]
            v = tool_get({"ns": ns, "subs": [k]}).get("value", "")
            keys.append(f"^{ns}('{k}') = {str(v)[:60]}")
        return "\n".join(keys[:20]) + (f"\n...{len(keys)-20} more" if len(keys)>20 else "")
    except Exception as e: return f"Error: {e}"

def cmd_zr():
    try:
        routines = []; k = ""
        for _ in range(200):
            r = tool_order({"ns": "ROUTINE", "subs": [k], "direction": 1})
            if not r.get("success") or not r.get("value"): break
            k = r["value"]
            if not k.startswith("BC_"): routines.append(k)
        return "\n".join(sorted(routines)[:30]) + (f"\n...{len(routines)-30} more" if len(routines)>30 else "")
    except Exception as e: return f"Error: {e}"

# ── WebSocket ──
import websockets

async def ws_handler(ws):
    # Sesión persistente: un StackVM por conexión
    vm = StackVM()
    
    await ws.send(json.dumps({"type": "output", "text": "M-Light v2 ready"}))
    async for msg in ws:
        try: data = json.loads(msg)
        except: continue
        line = data.get("line", "").strip()
        if not line: continue
        
        if line == "/help" or line == "?":
            await ws.send(json.dumps({"type": "output", "text": cmd_help()}))
        elif line.upper().startswith("D ^%SS"):
            await ws.send(json.dumps({"type": "output", "text": cmd_ss()}))
        elif line.upper().startswith("ZW ^"):
            ns = line[3:].strip().lstrip("^")
            await ws.send(json.dumps({"type": "output", "text": cmd_zw(ns)}))
        elif line.upper() == "ZR":
            await ws.send(json.dumps({"type": "output", "text": cmd_zr()}))
        elif line.upper() == "ZJOB":
            await ws.send(json.dumps({"type": "output", "text": "Active: 0"}))
        elif line.startswith("/ai "):
            await ws.send(json.dumps({"type": "ai", "text": f"; AI: {line[4:]}\nGEN\n S result=\"TODO\"\n W result\n Q"}))
        else:
            try:
                # Compilar y ejecutar sobre el mismo VM (sesión persistente)
                vm.compile(line)
                vm.exec()
                out = " ".join(str(o) for o in vm.ops if o is not None) or "OK"
                vm.ops = []  # Limpiar ops para siguiente comando
                await ws.send(json.dumps({"type": "output", "text": out}))
            except Exception as e:
                await ws.send(json.dumps({"type": "error", "text": str(e)}))

# ── HTTP ──
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE.encode())

def run_http(port):
    HTTPServer(("0.0.0.0", port+1), H).serve_forever()

async def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8082
    threading.Thread(target=run_http, args=(port,), daemon=True).start()
    print(f"  🌐 http://localhost:{port+1}")
    print(f"  ⚡ ws://localhost:{port}/ws")
    async with websockets.serve(ws_handler, "0.0.0.0", port):
        print("  🟢 Console ready!")
        await asyncio.Future()

if __name__ == "__main__":
    print("🚀 M-Light Console")
    asyncio.run(main())
