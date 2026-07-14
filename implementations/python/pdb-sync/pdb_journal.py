#!/usr/bin/env python3
"""
pdb_journal.py — WAL con source tagging para replicación PDB.

Cada escritura genera un entry en:
  ^CHANGES("journal", ts_iso, ns, key) = {value, source, op, clock}

Anti-bucle: source="local" → se replica. source="cloud" → no se re-replica.
"""

import json, os, sys
import _paths  # rutas repo-relativas
from datetime import datetime, timezone

JOURNAL_NS = "CHANGES"
JOURNAL_SUB = "journal"

def _tools():
    sp = _paths.PDB_DIR_S
    if sp not in sys.path: sys.path.insert(0, sp)
    from pdb_tools import tool_set, tool_kill, tool_order, tool_get
    return tool_set, tool_kill, tool_order, tool_get

def make_entry(ns, key, value, op="set", source="local", clock=None):
    return {
        "value": value, "source": source,
        "ts": datetime.now(timezone.utc).isoformat(),
        "op": op, "ns": ns, "key": key,
        "clock": clock or [],
    }

def write(entry):
    try:
        ts = entry["ts"]; ns = entry["ns"]; key = entry["key"]
        tool_set, _, _, _ = _tools()
        tool_set({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, ts, ns, key],
                  "value": json.dumps({k:v for k,v in entry.items() if k not in ("ns","key")})})
        return {"ok": True, "ts": ts}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def read(source=None, since=None, limit=100):
    try:
        _, _, o, g = _tools()
        entries = []; ts = since or ""
        while len(entries) < limit:
            r = o({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, ts], "direction": 1})
            if not r.get("success") or not r.get("value"): break
            ts = r["value"]
            # Iterar todos los namespaces en este timestamp
            ns = ""
            while len(entries) < limit:
                r2 = o({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, ts, ns], "direction": 1})
                if not r2.get("success") or not r2.get("value"): break
                ns = r2["value"]
                # Iterar todas las keys en este namespace
                key = ""
                while len(entries) < limit:
                    r3 = o({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, ts, ns, key], "direction": 1})
                    if not r3.get("success") or not r3.get("value"): break
                    key = r3["value"]
                    r4 = g({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, ts, ns, key]})
                    if r4.get("success") and r4.get("value"):
                        e = json.loads(r4["value"])
                        e["ns"] = ns; e["key"] = key; e["ts"] = ts
                        if source is None or e.get("source") == source:
                            entries.append(e)
        return entries
    except: return []

def pending():
    return len(read(source="local"))

def purge(older_than=None):
    try:
        _, k, o, _ = _tools(); ts = ""; n = 0
        while True:
            r = o({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, ts], "direction": 1})
            if not r.get("success") or not r.get("value"): break
            ts = r["value"]
            if older_than and ts >= older_than: break
            k({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, ts]}); n += 1
        return n
    except: return 0

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "demo"
    if cmd == "write":
        ns = sys.argv[2] if len(sys.argv) > 2 else "TEST"
        key = sys.argv[3] if len(sys.argv) > 3 else "t"
        val = sys.argv[4] if len(sys.argv) > 4 else "v"
        src = sys.argv[5] if len(sys.argv) > 5 else "local"
        print(write(make_entry(ns, key, val, source=src)))
    elif cmd == "read":
        src = sys.argv[2] if len(sys.argv) > 2 else None
        for e in read(source=src, limit=10):
            print(f"  [{e.get('source')}] {e.get('ns')}:{e.get('key')} = {str(e.get('value',''))[:40]}")
    elif cmd == "pending":
        print(f"Pending: {pending()}")
    elif cmd == "purge":
        print(f"Purged: {purge()}")
