"""Add /m endpoint to dashboard server for M-Light console."""
import os

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'thinking', 'server.py')
with open(path, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Marker to find where to insert
marker = 'elif self.path == "/wiki":\n                try:'

# The /m endpoint to insert before /wiki
mlight_handler = '''elif self.path == "/m":
                try:
                    content_len = int(self.headers.get('Content-Length', 0))
                    raw = self.rfile.read(content_len) if content_len else b'{}'
                    params = json.loads(raw)
                    code = params.get("code", "").strip()
                    if not code:
                        self.send_response(400); self.end_headers()
                        self.wfile.write(b'{"error":"code required"}'); return
                    # Import M-Light + PDB
                    import importlib.util as _iu, sys as _sys
                    _p = __import__('os').path
                    _dir = _p.dirname(_p.abspath(__file__))
                    _mp = _p.join(_dir, '..', 'pdb', 'm_light.py')
                    _ms = _iu.spec_from_file_location('m_light', _mp)
                    _mm = _iu.module_from_spec(_ms)
                    _ms.loader.exec_module(_mm)
                    _ps = _p.join(_dir, '..', 'pdb', 'pdb_tools.py')
                    _pdb_spec = _iu.spec_from_file_location('pdb_tools', _ps)
                    _pdb = _iu.module_from_spec(_pdb_spec)
                    _pdb_spec.loader.exec_module(_pdb)
                    encoder = _mm.MEvaluator(_pdb)
                    result = encoder.eval(code)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"code": code, "result": str(result) if result is not None else ""}).encode())
                except Exception as e:
                    self.send_response(500); self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
elif self.path == "/wiki":
                try:'''

if marker in content:
    content = content.replace(marker, mlight_handler, 1)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('✅ /m endpoint added to server.py')
else:
    print('❌ Marker not found')
