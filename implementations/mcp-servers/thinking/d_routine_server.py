"""
D ^ROUTINE Web — MSM-style panels for PDB/LUMEN.

Endpoints:
  /ss   → D ^SS: procesos activos (agentes, works, locks, chains)
  /gs   → D ^GS: navegador de globals con $ORDER drill-down
  /     → HTML index con ambos paneles

Lee directamente de PDB (lumen-pdb.db) y del thinking server via /metrics.
"""

import json, os, sqlite3, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

PDB_PATH = os.environ.get("PDB_PATH") or str(
    Path(__file__).resolve().parent.parent / "pdb" / "lumen-pdb.db"
)

def get_pdb_conn():
    conn = sqlite3.connect(PDB_PATH, timeout=3)
    conn.row_factory = sqlite3.Row
    return conn

def get_namespaces():
    conn = get_pdb_conn()
    rows = conn.execute(
        "SELECT ns, COUNT(*) as n, SUM(LENGTH(value)) as bytes FROM _globals GROUP BY ns ORDER BY bytes DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_ns_content(ns, prefix_subs=None):
    """Obtener subíndices de primer nivel para un namespace, con $ORDER semantics."""
    conn = get_pdb_conn()
    if prefix_subs is None:
        # Primer nivel: todos los subíndices directos
        rows = conn.execute(
            "SELECT subkey, value FROM _globals WHERE ns=? AND subkey NOT LIKE ? ORDER BY subkey LIMIT 100",
            [ns, b'\x00%']
        ).fetchall()
    else:
        # Nivel anidado
        prefix = b''
        for s in prefix_subs:
            if isinstance(s, str):
                prefix += b'\x02' + s.encode() + b'\xff'
            else:
                import struct
                raw = struct.pack('>d', float(s))
                prefix += b'\x01' + raw + b'\xff'
        rows = conn.execute(
            "SELECT subkey, value FROM _globals WHERE ns=? AND subkey >= ? AND subkey < ? ORDER BY subkey LIMIT 100",
            [ns, prefix, prefix + b'\xff\xff\xff\xff']
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_processes():
    """Leer procesos activos del thinking server via PDB STATE."""
    conn = get_pdb_conn()
    rows = conn.execute(
        "SELECT subkey, value FROM _globals WHERE ns='STATE' AND CAST(subkey AS TEXT) LIKE '%session%' AND CAST(subkey AS TEXT) LIKE '%work%' ORDER BY subkey"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

HTML_INDEX = """<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>D ^ROUTINE — PDB Control Panel</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Cascadia Code','Fira Code',monospace; background:#0a0a0f; color:#c0caf5; padding:20px; }
h1 { color:#7aa2f7; font-size:1.4em; margin-bottom:20px; }
h2 { color:#bb9af7; font-size:1.1em; margin:20px 0 10px; }
.nav { display:flex; gap:10px; margin-bottom:20px; }
.nav a { color:#7dcfff; text-decoration:none; padding:6px 14px; border:1px solid #1a1b26; border-radius:4px; }
.nav a:hover { background:#1a1b26; }
table { border-collapse:collapse; width:100%; margin:10px 0; font-size:0.85em; }
th, td { text-align:left; padding:6px 10px; border-bottom:1px solid #1a1b26; }
th { color:#7aa2f7; }
td { color:#c0caf5; }
.panel { background:#111118; border-radius:8px; padding:16px; margin:10px 0; }
.status-ok { color:#9ece6a; }
.status-warn { color:#e0af68; }
.status-err { color:#f7768e; }
pre { background:#0a0a0f; padding:10px; border-radius:4px; overflow-x:auto; font-size:0.8em; }
.badge { display:inline-block; padding:2px 8px; border-radius:10px; font-size:0.75em; }
.badge-blue { background:#1a1b26; color:#7aa2f7; }
.badge-purple { background:#1a1b26; color:#bb9af7; }
</style></head>
<body>
<h1>◆ D ^ROUTINE — PDB Control Panel</h1>
<div class="nav">
<a href="/ss">📋 D ^SS Procesos</a>
<a href="/gs">🔍 D ^GS Globals</a>
</div>
<div id="content">Loading...</div>
<script>
async function load(url) {
  const r = await fetch(url);
  const data = await r.json();
  document.getElementById('content').innerHTML = render(data);
}
function render(data) {
  if (data.type === 'ss') return renderSS(data);
  if (data.type === 'gs') return renderGS(data);
  return '<pre>'+JSON.stringify(data,null,2)+'</pre>';
}
function renderSS(d) {
  let h = '<div class="panel"><h2>📋 D ^SS — Procesos Activos</h2>';
  h += '<p>Namespaces: ' + (d.namespaces||[]).length + ' | Total records: ' + (d.total_records||0) + '</p>';
  h += '<table><tr><th>Namespace</th><th>Records</th><th>Size</th></tr>';
  for (const ns of d.namespaces||[]) {
    h += '<tr><td>^' + ns.ns + '</td><td>' + ns.n + '</td><td>' + (ns.bytes/1024).toFixed(1) + ' KB</td></tr>';
  }
  h += '</table></div>';
  return h;
}
function renderGS(d) {
  let h = '<div class="panel"><h2>🔍 D ^GS — Navegador de Globals</h2>';
  h += '<table><tr><th>Global</th><th>Registros</th><th>Tamaño</th><th></th></tr>';
  for (const ns of d.namespaces||[]) {
    h += '<tr><td>^' + ns.ns + '</td><td>' + ns.n + '</td><td>' + (ns.bytes/1024).toFixed(1) + ' KB</td>';
    h += '<td><a href="/gs/'+ns.ns+'" style="color:#7dcfff">▶ drill-down</a></td></tr>';
  }
  h += '</table></div>';
  return h;
}
load('/ss');
</script>
</body></html>"""

class DRoutineHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self._html(200, HTML_INDEX)
        elif self.path == '/ss':
            self._json(200, self._get_ss())
        elif self.path.startswith('/gs'):
            parts = self.path.split('/')
            if len(parts) >= 3:
                ns = parts[2]
                subs = parts[3:] if len(parts) > 3 else []
                self._json(200, self._get_gs(ns, subs))
            else:
                self._json(200, self._get_gs())
        else:
            self._json(404, {"error": "not found"})

    def _get_ss(self):
        namespaces = get_namespaces()
        procs = get_processes()
        return {
            "type": "ss",
            "total_records": sum(n['n'] for n in namespaces),
            "namespaces": namespaces,
            "processes": len(procs),
        }

    def _get_gs(self, ns=None, subs=None):
        namespaces = get_namespaces()
        if ns:
            content = get_ns_content(ns, subs)
            return {"type": "gs", "ns": ns, "content": content}
        return {"type": "gs", "namespaces": namespaces}

    def _html(self, code, body):
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(body.encode())

    def _json(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, fmt, *args):
        print(f"[D^ROUTINE] {args[0]} {args[1]} {args[2]}")

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8767
    server = HTTPServer(('127.0.0.1', port), DRoutineHandler)
    print(f"⚡ D ^ROUTINE web on http://127.0.0.1:{port}/")
    print(f"   D ^SS: http://127.0.0.1:{port}/ss")
    print(f"   D ^GS: http://127.0.0.1:{port}/gs")
    server.serve_forever()
