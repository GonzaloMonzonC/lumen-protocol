"""MsmConnection v2 — Conexión duck-type completa para pdb_tools.
Soporta todos los patrones SQL que usan tool_get, tool_order, tool_query.
"""
import json, os, struct, sys, re, sqlite3

CACHE_DIR = os.path.expanduser("~/Documents/GitHub/pdb-msm-importer/cache")
_cache = {}

def _decode_subkey(subkey: bytes) -> list:
    subs, i = [], 0
    while i < len(subkey):
        if subkey[i] == 0x02:
            i += 1
            if i < len(subkey) and subkey[i] == 0xFF: subs.append(""); i += 1
            else:
                end = subkey.find(b'\xff', i)
                if end == -1: break
                subs.append(subkey[i:end].decode('utf-8', errors='replace'))
                i = end + 1
        elif subkey[i] == 0x01:
            i += 1
            if i + 8 <= len(subkey):
                subs.append(struct.unpack('>d', subkey[i:i+8])[0])
                i += 9
            else: break
        elif subkey[i] == 0x00: subs.append(None); i += 1
        else: break
    return subs

def _encode_key(gname: str, key: str) -> bytes:
    return b'\x02' + gname.encode() + b'\xff' + b'\x02' + key.encode() + b'\xff'

def _load_cache(msm_name):
    if msm_name in _cache: return _cache[msm_name]
    cp = os.path.join(CACHE_DIR, msm_name + '.index.json')
    if not os.path.exists(cp): return None
    with open(cp) as f: idx = json.load(f)
    _cache[msm_name] = idx
    return idx

class MsmConnection:
    def __init__(self, msm_path):
        self.msm_name = os.path.basename(msm_path)
        self._rows, self._idx = [], None
    
    def _get_index(self):
        if self._idx is None: self._idx = _load_cache(self.msm_name)
        return self._idx
    
    def execute(self, sql, params=None):
        self._rows = []
        idx = self._get_index()
        if idx is None or not params or len(params) < 2: return self
        
        sql_up = sql.strip().upper()
        ns_key = params[0]
        
        # ── SELECT subkey FROM _globals WHERE ... (tool_order) ──
        if sql_up.startswith('SELECT SUBKEY'):
            return self._order(sql, params, idx)
        
        # ── SELECT value / SELECT 1 (tool_get / tool_has) ──
        if sql_up.startswith('SELECT VALUE') or sql_up.startswith('SELECT 1'):
            is_has = sql_up.startswith('SELECT 1')
            sb = self._tobytes(params[1])
            subs = _decode_subkey(sb) if isinstance(sb, bytes) else []
            if not subs: return self
            entries = idx.get(subs[0], {})
            if not entries: return self
            if is_has:
                self._rows = [{"value": 1}]
                return self
            target = subs[1] if len(subs) > 1 else None
            if target:
                for k, v in entries.items():
                    if k == target or (isinstance(target, str) and (target in k or k in target)):
                        self._rows = [{"value": v}]; return self
                return self
            for k, v in list(entries.items())[:1]:
                self._rows = [{"value": v}]; return self
            return self
        
        # ── SELECT subkey, value FROM _globals WHERE ns=? ... (tool_query / DDP) ──
        if sql_up.startswith('SELECT SUBKEY,'):
            return self._query(sql, params, idx)
        
        return self
    
    def _order(self, sql, params, idx):
        sb = self._tobytes(params[1])
        search_subs = _decode_subkey(sb) if isinstance(sb, bytes) else []
        if not search_subs: return self
        gname = search_subs[0]
        entries = idx.get(gname, {})
        if not entries: return self
        
        op = re.search(r'SUBKEY\s*(>=|<=|>|<)', sql, re.I)
        op = op.group(1) if op else '>'
        order = re.search(r'ORDER BY SUBKEY\s+(ASC|DESC)', sql, re.I)
        order = order.group(1).upper() if order else 'ASC'
        lim = re.search(r'LIMIT\s+(\d+)', sql, re.I)
        lim = int(lim.group(1)) if lim else 50
        off = re.search(r'OFFSET\s+(\d+)', sql, re.I)
        off = int(off.group(1)) if off else 0
        
        candidates = sorted([_encode_key(gname, k) for k in entries])
        if order == 'DESC': candidates.reverse()
        
        filtered = []
        for ck in candidates:
            if op == '>' and ck > sb: filtered.append(ck)
            elif op == '>=' and ck >= sb: filtered.append(ck)
            elif op == '<' and ck < sb: filtered.append(ck)
            elif op == '<=' and ck <= sb: filtered.append(ck)
        
        self._rows = [{"subkey": k} for k in filtered[off:off+lim]]
        return self
    
    def _query(self, sql, params, idx):
        """SELECT subkey, value FROM _globals WHERE ns=? ..."""
        ns = params[0]
        all_rows = []
        for gname, entries in idx.items():
            for key, val in entries.items():
                sk = _encode_key(gname, key)
                all_rows.append({"subkey": sk, "value": val})
        
        # Parse LIMIT/OFFSET
        lim = re.search(r'LIMIT\s+(\d+)', sql, re.I)
        lim = int(lim.group(1)) if lim else 100
        off = re.search(r'OFFSET\s+(\d+)', sql, re.I)
        off = int(off.group(1)) if off else 0
        
        self._rows = sorted(all_rows, key=lambda r: r["subkey"])[off:off+lim]
        return self
    
    def _tobytes(self, val):
        if isinstance(val, bytes): return val
        if isinstance(val, str):
            try:
                if len(val) > 10 and all(c in '0123456789abcdef' for c in val.lower()):
                    return bytes.fromhex(val)
            except: pass
            return val.encode()
        return b''
    
    def fetchone(self):
        return self._rows.pop(0) if self._rows else None
    
    def fetchall(self):
        r, self._rows = self._rows, []
        return r
    
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): self.close()
