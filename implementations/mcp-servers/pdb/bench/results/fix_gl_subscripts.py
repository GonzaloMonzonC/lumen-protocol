"""Fix %GL to support subscript notation: ^NS(subs1,subs2)"""
import os, re, sys

path = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking\server.py'
with open(path, 'r') as f:
    content = f.read()

# Find the %GL handler boundary - it starts with 'if code.upper().startswith("D ^%GL")'
# and ends at the next 'if' at the same indentation level
lines = content.split('\n')
start = None
depth = 0
for i, line in enumerate(lines):
    stripped = line.strip()
    if 'code.upper().startswith("D ^%GL' in stripped or 'code.upper() in ("D ^%GL"' in stripped:
        start = i
        break

if start is None:
    print('ERROR: Could not find %GL handler')
    sys.exit(1)

# Find the end: next top-level 'if' or 'except' at same indent
base_indent = len(lines[start]) - len(lines[start].lstrip())
end = start + 1
while end < len(lines):
    s = lines[end].strip()
    if s.startswith('if ') or s.startswith('elif '):
        indent = len(lines[end]) - len(lines[end].lstrip())
        if indent == base_indent:
            break
    end += 1

print(f'Replaced lines {start+1}-{end} ({end-start} lines)')

# The new handler code
new_lines = []
def a(l): new_lines.append(' ' * 24 + l)

new_lines.append('if code.upper().startswith("D ^%GL") or code.upper() in ("^%GL", "%GL"):')
new_lines.append(' ' * 24 + 'try:')
a('import sqlite3, os as _osx, re as _re, sys as _sys, json as _json')
a('_dbp = _osx.path.join(_osx.path.dirname(_osx.path.abspath(__file__)), "..", "pdb", "lumen-pdb.db")')
a('_cx = sqlite3.connect(_dbp)')
a('_sys.path.insert(0, _osx.path.join(_osx.path.dirname(_osx.path.abspath(__file__)), "..", "pdb"))')
a('import importlib.util as _iu')
a('_pdb_s = _iu.spec_from_file_location("_pdb_dec", _osx.path.join(_osx.path.dirname(_osx.path.abspath(__file__)), "..", "pdb", "pdb_tools.py"))')
a('_pdb_m = _iu.module_from_spec(_pdb_s)')
a('_pdb_s.loader.exec_module(_pdb_m)')
a('_enc = _pdb_m.encode_subkey')
a('_dec = _pdb_m.decode_subkey')
a('_arg = code.strip()')
a('_m = _re.search(r"\\\\^(\\\\w+)(?:\\\\(([^)]+)\\\\))?", _arg)')
a('_ns = _m.group(1).upper() if _m else ""')
a('_subs_str = _m.group(2) if _m and _m.group(2) else ""')
a('_subs = []')
a('if _subs_str:')
a('    _subs = [s.strip() for s in _subs_str.split(",")]')
a('if not _ns or _ns in ("%GL", "D"):')
a('    _cur = _cx.execute("SELECT ns, COUNT(*) as c FROM _globals GROUP BY ns ORDER BY ns")')
a('    _lines = [ns + ": " + str(c) + " nodes" for ns, c in _cur.fetchall() if ns and len(ns) < 30 and not ns.startswith("<")]')
a('    result = chr(10).join(_lines) if _lines else "No globals found"')
a('    result += chr(10) + chr(10) + "Total: " + str(len(_lines)) + " namespaces"')
a('else:')
a('    if not _subs:')
a('        _cur = _cx.execute("SELECT subkey, value FROM _globals WHERE ns=? LIMIT 5", [_ns])')
a('        _cnt = _cx.execute("SELECT COUNT(*) FROM _globals WHERE ns=?", [_ns]).fetchone()[0]')
a('        result = "^" + _ns + ": " + str(_cnt) + " nodes"')
a('        for sk, val in _cur.fetchall():')
a('            if isinstance(val, bytes): val = val.decode("utf-8","replace")[:80]')
a('            try: val = _json.loads(val) if isinstance(val, str) and val and val[0] == \'"\' else val')
a('            except: pass')
a('            if isinstance(sk, bytes):')
a('                try:')
a('                    _d = _dec(sk)')
a('                    sk_str = ",".join(str(s) for s in _d)')
a('                except:')
a('                    sk_str = sk.hex()[:40]')
a('            else:')
a('                sk_str = str(sk)[:40]')
a('            result += chr(10) + "  " + sk_str + " = " + str(val)')
a('    else:')
a('        _skey = _enc(_subs)')
a('        _cur = _cx.execute("SELECT subkey, value FROM _globals WHERE ns=? AND subkey >= ? AND subkey < ? || x\'ff\' LIMIT 10", [_ns, _skey, _skey])')
a('        _rows = _cur.fetchall()')
a('        if not _rows:')
a('            _cur2 = _cx.execute("SELECT value FROM _globals WHERE ns=? AND subkey=?", [_ns, _skey])')
a('            _val = _cur2.fetchone()')
a('            if _val:')
a('                v = _val[0]')
a('                if isinstance(v, bytes): v = v.decode("utf-8","replace")')
a('                try: v = _json.loads(v) if isinstance(v, str) and v and v[0] == \'"\' else v')
a('                except: pass')
a('                result = "^" + _ns + "(" + _subs_str + ") = " + str(v)')
a('            else:')
a('                result = "^" + _ns + "(" + _subs_str + "): not found"')
a('        else:')
a('            result = "^" + _ns + "(" + _subs_str + "):"')
a('            for sk, val in _rows:')
a('                if isinstance(val, bytes): val = val.decode("utf-8","replace")[:80]')
a('                try: val = _json.loads(val) if isinstance(val, str) and val and val[0] == \'"\' else val')
a('                except: pass')
a('                if isinstance(sk, bytes):')
a('                    try:')
a('                        _d = _dec(sk)')
a('                        _child = ",".join(str(s) for s in _d[len(_subs):])')
a('                    except:')
a('                        _child = sk.hex()[:40]')
a('                else:')
a('                    _child = str(sk)[:40]')
a('                result += chr(10) + "  " + _child + " = " + str(val)')
a('self.send_response(200)')
a('self.send_header("Content-Type", "application/json")')
a('self.end_headers()')
a('self.wfile.write(_json.dumps({"code": code, "result": result}).encode())')
a('return')
new_lines.append(' ' * 24 + 'except Exception as e:')
a('import json as _json')
a('self.send_response(200)')
a('self.send_header("Content-Type", "application/json")')
a('self.end_headers()')
a('self.wfile.write(_json.dumps({"code": code, "result": "Error: " + str(e)}).encode())')
a('return')

# Replace
new_content = '\n'.join(lines[:start]) + '\n' + '\n'.join(new_lines) + '\n' + '\n'.join(lines[end:])
with open(path, 'w') as f:
    f.write(new_content)
print('Done. File rewritten.')
