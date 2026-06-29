#!/usr/bin/env python3
"""Replace %GL handler using line-level precision."""
import os

path = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking\server.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')

# Find the %GL handler start
start_i = None
for i, line in enumerate(lines):
    if 'code.upper() in ("D ^%GL", "^%GL", "%GL")' in line:
        start_i = i
        break

# %SS handler starts at: if code.upper().startswith("D ^%SS")
end_i = None
for i in range(start_i + 1, len(lines)):
    if 'startswith("D ^%SS")' in lines[i]:
        end_i = i
        break

print(f'Old handler: line {start_i+1} to {end_i} ({end_i-start_i} lines)')

# New handler
INDENT = '                    '  # 20 spaces
I2 = '                        '  # 24
I3 = '                            '  # 28
I4 = '                                '  # 32
I5 = '                                    '  # 36
I6 = '                                        '  # 40

new_handler = f'''{INDENT}if code.upper() in ("D ^%GL", "^%GL", "%GL") or code.upper().startswith("D ^%GL ") or code.upper().startswith("^%GL "):
{I2}try:
{I3}import sqlite3, os as _osx, re as _re, json as _json, sys as _sys
{I3}import importlib.util as _iu
{I3}_pd = _osx.path.join(_osx.path.dirname(_osx.path.abspath(__file__)), "..", "pdb")
{I3}_sys.path.insert(0, _pd)
{I3}_pdb_s = _iu.spec_from_file_location("_pdb_dec", _osx.path.join(_pd, "pdb_tools.py"))
{I3}_pdb_m = _iu.module_from_spec(_pdb_s)
{I3}_pdb_s.loader.exec_module(_pdb_m)
{I3}_enc = _pdb_m.encode_subkey
{I3}_dec = _pdb_m.decode_subkey
{I3}_dbp = _osx.path.join(_pd, "lumen-pdb.db")
{I3}_cx = sqlite3.connect(_dbp)
{I3}_arg = code.strip()
{I3}_m = _re.search(r"\\\\^(\\\\w+)", _arg)
{I3}_ns = _m.group(1).upper() if _m else ""
{I3}_m2 = _re.search(r"\\\\\(([^)]+)\\\\)", _arg)
{I3}_subs_str = _m2.group(1) if _m2 else ""
{I3}_subs_list = [s.strip() for s in _subs_str.split(",")] if _subs_str else []
{I3}if not _ns or _ns in ("%GL", "D"):
{I4}# List all namespaces
{I4}_cur = _cx.execute("SELECT ns, COUNT(*) as c FROM _globals GROUP BY ns ORDER BY ns")
{I4}_lines = [ns + ": " + str(c) + " nodes" for ns, c in _cur.fetchall() if ns and len(ns) < 30 and not ns.startswith("<")]
{I4}result = chr(10).join(_lines) if _lines else "No globals found"
{I4}result += chr(10) + chr(10) + "Total: " + str(len(_lines)) + " namespaces"
{I3}else:
{I4}if _subs_list:
{I5}_skey = _enc(_subs_list)
{I5}_cur = _cx.execute("SELECT subkey, value FROM _globals WHERE ns=? AND subkey >= ? AND subkey < ? || x'ff' LIMIT 10", [_ns, _skey, _skey])
{I5}_rows = _cur.fetchall()
{I5}if not _rows:
{I6}_cur2 = _cx.execute("SELECT value FROM _globals WHERE ns=? AND subkey=?", [_ns, _skey])
{I6}_val = _cur2.fetchone()
{I6}if _val:
{I6}v = _val[0]
{I6}if isinstance(v, bytes): v = v.decode("utf-8","replace")
{I6}try: v = _json.loads(v) if isinstance(v, str) and v and v[0] == '"' else v
{I6}except: pass
{I6}result = "^" + _ns + "(" + _subs_str + ") = " + str(v)
{I6}else:
{I6}result = "^" + _ns + "(" + _subs_str + "): not found"
{I5}else:
{I6}result = "^" + _ns + "(" + _subs_str + "):"
{I6}for sk, val in _rows:
{I6}if isinstance(val, bytes): val = val.decode("utf-8","replace")[:80]
{I6}try: val = _json.loads(val) if isinstance(val, str) and val and val[0] == '"' else val
{I6}except: pass
{I6}if isinstance(sk, bytes):
{I6}try:
{I6}_d = _dec(sk)
{I6}_child = ",".join(str(s) for s in _d[len(_subs_list):])
{I6}except:
{I6}_child = sk.hex()[:40]
{I6}else:
{I6}_child = str(sk)[:40]
{I6}result += chr(10) + "  " + _child + " = " + str(val)
{I4}else:
{I5}_cnt = _cx.execute("SELECT COUNT(*) FROM _globals WHERE ns=?", [_ns]).fetchone()[0]
{I5}_cur = _cx.execute("SELECT subkey, value FROM _globals WHERE ns=? LIMIT 5", [_ns])
{I5}result = "^" + _ns + ": " + str(_cnt) + " nodes"
{I5}for sk, val in _cur.fetchall():
{I6}if isinstance(val, bytes): val = val.decode("utf-8","replace")[:80]
{I6}try: val = _json.loads(val) if isinstance(val, str) and val and val[0] == '"' else val
{I6}except: pass
{I6}if isinstance(sk, bytes):
{I6}try:
{I6}_d = _dec(sk)
{I6}sk_str = ",".join(str(s) for s in _d)
{I6}except:
{I6}sk_str = sk.hex()[:40]
{I6}else:
{I6}sk_str = str(sk)[:40]
{I6}result += chr(10) + "  " + sk_str + " = " + str(val)
{I3}self.send_response(200)
{I3}self.send_header("Content-Type", "application/json")
{I3}self.end_headers()
{I3}self.wfile.write(_json.dumps({{"code": code, "result": result}}).encode())
{I3}return
{I2}except Exception as e:
{I3}self.send_response(200)
{I3}self.send_header("Content-Type", "application/json")
{I3}self.end_headers()
{I3}self.wfile.write(_json.dumps({{"code": code, "result": "Error: " + str(e)}}).encode())
{I3}return'''

# Replace lines start_i .. end_i-1 with new_handler
new_content = '\n'.join(lines[:start_i]) + '\n' + new_handler + '\n' + '\n'.join(lines[end_i:])

with open(path, 'w', encoding='utf-8') as f:
    f.write(new_content)

# Verify
import py_compile
try:
    py_compile.compile(path, doraise=True)
    print('✅ Syntax OK')
    print(f'Replaced {end_i-start_i} lines at {start_i+1}')
except py_compile.PyCompileError as e:
    print(f'❌ Error: {e}')
    # Restore
    os.system('git checkout ' + path)
