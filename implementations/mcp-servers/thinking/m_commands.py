"""MUMPS utility commands for the dashboard M Console."""
import sqlite3, os, re, json, sys
import importlib.util as _iu

_GL_STATE = None
_ENC_DEC = None

def _get_enc_dec():
    global _ENC_DEC
    if _ENC_DEC is None:
        _pd = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pdb')
        sys.path.insert(0, _pd)
        _pdb_s = _iu.spec_from_file_location('_pdb_dec', os.path.join(_pd, 'pdb_tools.py'))
        _pdb_m = _iu.module_from_spec(_pdb_s)
        _pdb_s.loader.exec_module(_pdb_m)
        _ENC_DEC = (_pdb_m.encode_subkey, _pdb_m.decode_subkey)
    return _ENC_DEC

def zw_handler(code):
    """Handle ZW (ZWRITE) commands.
    ZW ^GLOBAL              → show all entries
    ZW ^GLOBAL(sub1,sub2)   → show entry and children
    """
    _enc, _dec = _get_enc_dec()
    _pd = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pdb')
    _dbp = os.path.join(_pd, 'lumen-pdb.db')
    _cx = sqlite3.connect(_dbp)
    
    # Parse ^GLOBAL or ^GLOBAL(subs)
    _m = re.search(r'\^(\w+)', code)
    if not _m:
        return 'ZW: syntax error, expected ^GLOBAL or ^GLOBAL(subs)'
    _ns = _m.group(1).upper()
    
    _m2 = re.search(r'\(([^)]+)\)', code)
    _subs_str = _m2.group(1) if _m2 else ''
    _subs_list = [s.strip() for s in _subs_str.split(',')] if _subs_str else []
    
    if not _subs_list:
        # ZW ^GLOBAL → show ALL entries (limit 20)
        _cnt = _cx.execute("SELECT COUNT(*) FROM _globals WHERE ns=?", [_ns]).fetchone()[0]
        _cur = _cx.execute("SELECT subkey, value FROM _globals WHERE ns=? LIMIT 20", [_ns])
        result = '^' + _ns + ': ' + str(_cnt) + ' nodes\n'
        for sk, val in _cur.fetchall():
            if isinstance(val, bytes): val = val.decode('utf-8','replace')[:80]
            try: val = json.loads(val) if isinstance(val, str) and val and val[0] == '"' else val
            except: pass
            if isinstance(sk, bytes):
                try:
                    _d = _dec(sk)
                    # Format: ^GLOBAL(subs...) = value
                    _key = ','.join('"' + str(s) + '"' if isinstance(s, str) and ' ' in s else str(s) for s in _d)
                    result += '^' + _ns + '(' + _key + ') = ' + str(val) + '\n'
                except:
                    result += '  ' + sk.hex()[:40] + ' = ' + str(val) + '\n'
            else:
                result += '  ' + str(sk)[:40] + ' = ' + str(val) + '\n'
        if _cnt > 20:
            result += '... (' + str(_cnt - 20) + ' more nodes)'
    else:
        # ZW ^GLOBAL(subs) → show children
        _skey = _enc(_subs_list)
        _bound = _skey + b'\xff'
        _cur = _cx.execute("SELECT subkey, value FROM _globals WHERE ns=? AND subkey >= ? AND subkey < ? LIMIT 20", [_ns, _skey, _bound])
        _rows = _cur.fetchall()
        if not _rows:
            # Maybe it's a leaf with a value
            _val = _cx.execute("SELECT value FROM _globals WHERE ns=? AND subkey=?", [_ns, _skey]).fetchone()
            if _val:
                v = _val[0]
                if isinstance(v, bytes): v = v.decode('utf-8','replace')
                try: v = json.loads(v) if isinstance(v, str) and v and v[0] == '"' else v
                except: pass
                _key = '","'.join('"' + s + '"' if ' ' in s else s for s in _subs_list)
                result = '^' + _ns + '(' + ','.join(_subs_list) + ') = ' + str(v)
            else:
                result = '^' + _ns + '(' + ','.join(_subs_list) + '): not found'
        else:
            result = '^' + _ns + '(' + ','.join(_subs_list) + '):\n'
            for sk, val in _rows:
                if isinstance(val, bytes): val = val.decode('utf-8','replace')[:80]
                try: val = json.loads(val) if isinstance(val, str) and val and val[0] == '"' else val
                except: pass
                if isinstance(sk, bytes):
                    try:
                        _d = _dec(sk)
                        _child = ','.join(str(s) for s in _d[len(_subs_list):])
                        _key = '","'.join('"' + s + '"' if ' ' in s else s for s in _d)
                        result += '^' + _ns + '(' + _key + ') = ' + str(val) + '\n'
                    except:
                        result += '  ' + sk.hex()[:40] + ' = ' + str(val) + '\n'
                else:
                    result += '  ' + str(sk)[:40] + ' = ' + str(val) + '\n'
    
    _cx.close()
    return result

def gl_handler(code):
    """Handle D ^%GL commands with interactive state."""
    global _GL_STATE
    _enc, _dec = _get_enc_dec()
    _pd = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pdb')
    _dbp = os.path.join(_pd, 'lumen-pdb.db')
    _cx = sqlite3.connect(_dbp)
    _arg = code.strip()
    
    _matches = re.findall(r'(?:\^?%?\w+)', _arg)
    _all_globals = []
    for m in _matches:
        m = m.strip()
        if not m: continue
        um = m.upper()
        if um in ('%GL', '%SS', 'D', '^%GL', '^%SS', 'GL', 'SS'): continue
        if um.startswith('%'): continue
        if m.startswith('^'): m = m[1:]
        _all_globals.append(m.upper())
    
    _typed_ns = _all_globals[0] if _all_globals else ''
    _typed_subs_str = ''
    _m2 = re.search(r'\(([^)]*)\)', _arg)
    if _m2:
        _typed_subs_str = _m2.group(1).strip()
    
    if not _typed_ns:
        if _GL_STATE and _GL_STATE.get('mode') == 'browse':
            result = _show_next_page(_cx)
            _cx.close()
            return result
        _cur = _cx.execute("SELECT ns, COUNT(*) as c FROM _globals GROUP BY ns ORDER BY ns")
        _lines = [ns + ': ' + str(c) + ' nodes' for ns, c in _cur.fetchall() if ns and len(ns) < 30 and not ns.startswith('<')]
        result = '\n'.join(_lines) if _lines else 'No globals found'
        result += '\n\nTotal: ' + str(len(_lines)) + ' namespaces'
        result += '\n\nEnter a global name to browse, or %GL again for next page'
        _GL_STATE = {'mode': 'name', 'page': 0}
        _cx.close()
        return result
    
    _ns = _typed_ns
    _cnt = _cx.execute("SELECT COUNT(*) FROM _globals WHERE ns=?", [_ns]).fetchone()[0]
    if _cnt == 0:
        result = '^' + _ns + ': namespace not found'
        _cx.close()
        return result
    
    if not _typed_subs_str:
        _cur = _cx.execute("SELECT subkey, value FROM _globals WHERE ns=? LIMIT 5", [_ns])
        _rows = _cur.fetchall()
        result = '^' + _ns + ': ' + str(_cnt) + ' nodes\n'
        for sk, val in _rows:
            if isinstance(val, bytes): val = val.decode('utf-8','replace')[:60]
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
            result += '  ' + sk_str + ' = ' + str(val) + '\n'
        if _cnt > 5:
            result += '... (' + str(_cnt - 5) + ' more)'
            result += '\nEnter a subscript to drill down, or just Enter for next page'
            _GL_STATE = {'ns': _ns, 'mode': 'browse', 'page': 0, 'total': _cnt, 'offset': 5}
        else:
            _GL_STATE = None
    else:
        _subs_list = [s.strip() for s in _typed_subs_str.split(',')] if _typed_subs_str else []
        _skey = _enc(_subs_list)
        _bound = _skey + b'\xff'
        _exact = _cx.execute("SELECT value FROM _globals WHERE ns=? AND subkey=?", [_ns, _skey]).fetchone()
        if _exact:
            v = _exact[0]
            if isinstance(v, bytes): v = v.decode('utf-8','replace')
            try: v = json.loads(v) if isinstance(v, str) and v and v[0] == '"' else v
            except: pass
            result = '^' + _ns + '(' + _typed_subs_str + ') = ' + str(v)
            _GL_STATE = None
            _cx.close()
            return result
        
        _cur = _cx.execute("SELECT subkey, value FROM _globals WHERE ns=? AND subkey >= ? AND subkey < ? LIMIT 10", [_ns, _skey, _bound])
        _rows = _cur.fetchall()
        if _rows:
            result = '^' + _ns + '(' + _typed_subs_str + '):\n'
            for sk, val in _rows:
                if isinstance(val, bytes): val = val.decode('utf-8','replace')[:60]
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
                result += '  ' + _child + ' = ' + str(val) + '\n'
            _GL_STATE = {'ns': _ns, 'mode': 'browse', 'page': 0, 'total': _cnt}
        else:
            result = '^' + _ns + '(' + _typed_subs_str + '): not found'
            _GL_STATE = None
    
    _cx.close()
    return result

def _show_next_page(_cx):
    """Show next page of subscripts from current state."""
    global _GL_STATE
    _enc, _dec = _get_enc_dec()
    if not _GL_STATE or _GL_STATE.get('mode') != 'browse':
        return '(%GL finished)'
    _ns = _GL_STATE['ns']
    _offset = _GL_STATE.get('offset', 0)
    _page = _GL_STATE.get('page', 0) + 1
    _cur = _cx.execute("SELECT subkey, value FROM _globals WHERE ns=? LIMIT 5 OFFSET ?", [_ns, _offset])
    _rows = _cur.fetchall()
    _total = _GL_STATE.get('total', _cx.execute("SELECT COUNT(*) FROM _globals WHERE ns=?", [_ns]).fetchone()[0])
    if not _rows:
        _GL_STATE = None
        return '^' + _ns + ': end of data'
    result = '^' + _ns + ' (page ' + str(_page) + '):\n'
    for sk, val in _rows:
        if isinstance(val, bytes): val = val.decode('utf-8','replace')[:60]
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
        result += '  ' + sk_str + ' = ' + str(val) + '\n'
    _remaining = _total - _offset - len(_rows)
    if _remaining > 0:
        result += '... (' + str(_remaining) + ' more)'
        result += '\nPress Enter for next page, or type a new %GL command'
        _GL_STATE['offset'] = _offset + 5
        _GL_STATE['page'] = _page
    else:
        result += '\n(^' + _ns + ': all entries shown)'
        _GL_STATE = None
    return result

def reset_gl():
    global _GL_STATE
    _GL_STATE = None
