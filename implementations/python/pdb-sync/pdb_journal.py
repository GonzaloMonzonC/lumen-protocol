#!/usr/bin/env python3
"""
pdb_journal.py — journal DDP con seq monótono y source tagging (Fase 2).

Esquema v2:
  ^CHANGES("seq")            = contador atómico ($INCREMENT)
  ^CHANGES("journal", seq)   = {ns, key, value, source, op, ts, clock}
  ^CHANGES("cursor", name)   = último seq consumido por ese consumidor

Orden TOTAL de replay por seq — sin colisiones de timestamp (el esquema
v1 ^CHANGES("journal", ts_iso, ns, key) perdía entries con el mismo ts
y no daba orden estable). `migrate_legacy()` re-encola las entries v1.

Anti-bucle: source="local" → se replica. source="cloud" → no se re-replica.
"""

import json, sys
import _paths  # rutas repo-relativas
from datetime import datetime, timezone

JOURNAL_NS = "CHANGES"
JOURNAL_SUB = "journal"
SEQ_SUB = "seq"
CURSOR_SUB = "cursor"

def _tools():
    sp = _paths.PDB_DIR_S
    if sp not in sys.path: sys.path.insert(0, sp)
    from pdb_tools import tool_set, tool_kill, tool_order, tool_get, tool_incr
    return tool_set, tool_kill, tool_order, tool_get, tool_incr

def make_entry(ns, key, value, op="set", source="local", clock=None):
    return {
        "value": value, "source": source,
        "ts": datetime.now(timezone.utc).isoformat(),
        "op": op, "ns": ns, "key": key,
        "clock": clock or [],
    }

def _next_seq():
    _, _, _, _, incr = _tools()
    r = incr({"ns": JOURNAL_NS, "subs": [SEQ_SUB]})
    return int(r["value"])

def write(entry):
    try:
        s, _, _, _, _ = _tools()
        seq = _next_seq()
        s({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, seq],
           "value": json.dumps(entry)})
        return {"ok": True, "seq": seq, "ts": entry.get("ts")}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def read(source=None, since=None, limit=100):
    """Lee entries en orden de seq.

    since: int → seq exclusivo desde el que leer (cursor).
           str ISO (legacy) → filtra por entry["ts"] > since.
    Cada entry devuelta incluye "seq".
    """
    try:
        _, _, o, g, _ = _tools()
        since_seq = since if isinstance(since, (int, float)) else 0
        since_ts = since if isinstance(since, str) else None
        entries = []
        cur = since_seq
        while len(entries) < limit:
            r = o({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, cur], "direction": 1})
            if not r.get("success") or r.get("value") in ("", None): break
            cur = r["value"]
            if not isinstance(cur, (int, float)):
                break  # entries legacy (ts string) — usar migrate_legacy()
            r2 = g({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, cur]})
            if not (r2.get("success") and r2.get("value")): continue
            e = json.loads(r2["value"]) if isinstance(r2["value"], str) else r2["value"]
            e["seq"] = int(cur)
            if since_ts and e.get("ts", "") <= since_ts: continue
            if source is None or e.get("source") == source:
                entries.append(e)
        return entries
    except Exception:
        return []

def pending():
    return len(read(source="local"))

def last_seq():
    """Último seq asignado (0 si journal vacío)."""
    try:
        _, _, _, g, _ = _tools()
        r = g({"ns": JOURNAL_NS, "subs": [SEQ_SUB]})
        return int(r.get("value") or 0)
    except Exception:
        return 0

# ── Cursores por consumidor (push, changefeed...) ──

def cursor_get(name):
    try:
        _, _, _, g, _ = _tools()
        r = g({"ns": JOURNAL_NS, "subs": [CURSOR_SUB, name]})
        return int(r.get("value") or 0)
    except Exception:
        return 0

def cursor_set(name, seq):
    s, _, _, _, _ = _tools()
    s({"ns": JOURNAL_NS, "subs": [CURSOR_SUB, name], "value": int(seq)})
    return int(seq)

def read_after_cursor(name, source=None, limit=100):
    """Entries posteriores al cursor `name`. El llamante hace cursor_set
    con el seq del último entry procesado tras confirmar el envío."""
    return read(source=source, since=cursor_get(name), limit=limit)

def purge(older_than=None, up_to_seq=None, keep_cursors=True):
    """Borra entries del journal.

    up_to_seq: borra seq <= N (uso normal con cursores).
    older_than: ts ISO (legacy) — borra entries con ts < older_than.
    Sin args: borra todo el subárbol journal.
    """
    try:
        _, k, o, g, _ = _tools()
        n = 0
        cur = 0
        while True:
            r = o({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, cur], "direction": 1})
            if not r.get("success") or r.get("value") in ("", None): break
            cur = r["value"]
            if not isinstance(cur, (int, float)):
                # legacy ts-keyed: borra si older_than lo cubre (o siempre sin args)
                if older_than and str(cur) >= older_than: break
                k({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, cur]}); n += 1
                continue
            if up_to_seq is not None and cur > up_to_seq: break
            if older_than:
                r2 = g({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, cur]})
                e = {}
                try:
                    e = json.loads(r2.get("value") or "{}")
                except Exception:
                    pass
                if e.get("ts", "") >= older_than: continue
            k({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, cur]}); n += 1
        return n
    except Exception:
        return 0

# ── Migración v1 → v2 ──

def migrate_legacy():
    """Re-encola entries v1 ^CHANGES(journal, ts, ns, key) como seq v2.

    Orden de migración = orden de ts (el mejor orden total disponible en
    v1). Idempotente: borra cada entry v1 tras re-escribirla.
    """
    _, k, o, g, _ = _tools()
    migrated = 0
    while True:
        # los seq numéricos ordenan antes que los ts string: saltarlos
        ts = 0
        legacy_ts = None
        while True:
            r = o({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, ts], "direction": 1})
            if not r.get("success") or r.get("value") in ("", None): break
            ts = r["value"]
            if isinstance(ts, str):
                legacy_ts = ts
                break
        if legacy_ts is None:
            return migrated
        ns = ""
        while True:
            r2 = o({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, legacy_ts, ns], "direction": 1})
            if not r2.get("success") or r2.get("value") in ("", None): break
            ns = r2["value"]
            key = ""
            while True:
                r3 = o({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, legacy_ts, ns, key], "direction": 1})
                if not r3.get("success") or r3.get("value") in ("", None): break
                key = r3["value"]
                r4 = g({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, legacy_ts, ns, key]})
                if r4.get("success") and r4.get("value"):
                    try:
                        e = json.loads(r4["value"])
                    except Exception:
                        e = {"value": r4["value"], "source": "local", "op": "set"}
                    e.setdefault("ts", legacy_ts)
                    e["ns"] = ns; e["key"] = key
                    write(e)
                    migrated += 1
        k({"ns": JOURNAL_NS, "subs": [JOURNAL_SUB, legacy_ts]})

if __name__ == "__main__":
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
            print(f"  [{e.get('seq')}·{e.get('source')}] {e.get('ns')}:{e.get('key')} = {str(e.get('value',''))[:40]}")
    elif cmd == "pending":
        print(f"Pending: {pending()}")
    elif cmd == "purge":
        print(f"Purged: {purge()}")
    elif cmd == "migrate":
        print(f"Migradas: {migrate_legacy()}")
    elif cmd == "status":
        print(f"last_seq={last_seq()} pending={pending()} cursor_push={cursor_get('push')}")
