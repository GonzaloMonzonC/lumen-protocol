"""MUMPS utility commands for the dashboard M Console."""
import sqlite3, os, re, json, sys
import importlib.util as _iu

def gl_handler(code):
    """Handle D ^%GL commands with subscript support."""
    _pd = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pdb')
    sys.path.insert(0, _pd)
    _pdb_s = _iu.spec_from_file_location('_pdb_dec', os.path.join(_pd, 'pdb_tools.py'))
    _pdb_m = _iu.module_from_spec(_pdb_s)
    _pdb_s.loader.exec_module(_pdb_m)
    _enc = _pdb_m.encode_subkey
    _dec = _pdb_m.decode_subkey
    _dbp = os.path.join(_pd, 'lumen-pdb.db')
    _cx = sqlite3.connect(_dbp)
    _arg = code.strip()
    _matches = re.findall(r'\^?(\w+)', _arg)
    _all_globals = [m for m in _matches if m.upper() not in ('%GL', '%SS', 'D', '') and not m.startswith('%')]
    _ns = _all_globals[0].upper() if _all_globals else ''
    _m2 = re.search(r'\(([^)]+)\)', _arg)
    _subs_str = _m2.group(1) if _m2 else ''
    _subs_list = [s.strip() for s in _subs_str.split(',')] if _subs_str else []
    if not _ns or _ns in ('%GL', 'D'):
        _cur = _cx.execute("SELECT ns, COUNT(*) as c FROM _globals GROUP BY ns ORDER BY ns")
        _lines = [ns + ': ' + str(c) + ' nodes' for ns, c in _cur.fetchall() if ns and len(ns) < 30 and not ns.startswith('<')]
        result = '\n'.join(_lines) if _lines else 'No globals found'
        result += '\n\nTotal: ' + str(len(_lines)) + ' namespaces'
    else:
        if _subs_list:
            _skey = _enc(_subs_list)
            _bound = _skey + b'\xff'
            _cur = _cx.execute("SELECT subkey, value FROM _globals WHERE ns=? AND subkey >= ? AND subkey < ? LIMIT 10", [_ns, _skey, _bound])
            _rows = _cur.fetchall()
            if not _rows:
                _cur2 = _cx.execute("SELECT value FROM _globals WHERE ns=? AND subkey=?", [_ns, _skey])
                _val = _cur2.fetchone()
                if _val:
                    v = _val[0]
                    if isinstance(v, bytes): v = v.decode('utf-8','replace')
                    try: v = json.loads(v) if isinstance(v, str) and v and v[0] == '"' else v
                    except: pass
                    result = '^' + _ns + '(' + _subs_str + ') = ' + str(v)
                else:
                    result = '^' + _ns + '(' + _subs_str + '): not found'
            else:
                result = '^' + _ns + '(' + _subs_str + '):'
                for sk, val in _rows:
                    if isinstance(val, bytes): val = val.decode('utf-8','replace')[:80]
                    try: val = json.loads(val) if isinstance(val, str) and val and val[0] == '"' else val
                    except: pass
                    if isinstance(sk, bytes):
                        try:
                            _d = _dec(sk)
                            _child = ','.join(str(s) for s in _d[len(_subs_list):])
                        except:
                            _child = sk.hex()[:40]
                    else:
                        _child = str(sk)[:40]
                    result += '\n  ' + _child + ' = ' + str(val)
        else:
            _cnt = _cx.execute("SELECT COUNT(*) FROM _globals WHERE ns=?", [_ns]).fetchone()[0]
            _cur = _cx.execute("SELECT subkey, value FROM _globals WHERE ns=? LIMIT 5", [_ns])
            result = '^' + _ns + ': ' + str(_cnt) + ' nodes'
            for sk, val in _cur.fetchall():
                if isinstance(val, bytes): val = val.decode('utf-8','replace')[:80]
                try: val = json.loads(val) if isinstance(val, str) and val and val[0] == '"' else val
                except: pass
                if isinstance(sk, bytes):
                    try:
                        _d = _dec(sk)
                        sk_str = ','.join(str(s) for s in _d)
                    except:
                        sk_str = sk.hex()[:40]
                else:
                    sk_str = str(sk)[:40]
                result += '\n  ' + sk_str + ' = ' + str(val)
    _cx.close()
    return result
