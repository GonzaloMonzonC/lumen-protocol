#!/usr/bin/env python3
"""
pdb_sync_engine.py — DDP-04: Sync Engine (conflictos + heartbeat + anti-loop).

Arquitectura (Zalo):
- Source tagging: cada entry tiene source="local"|"cloud"
- Anti-bucle: entries con source == destino se saltan
- Fase 1: source tagging. Fase 2: vector clocks.

Flujo:
  LOCAL: write → journal(source=local) → DDP push → cloud
  CLOUD: DDP pull → journal(source=cloud) → apply local → anti-bucle
"""

import os, json, time, hashlib
import _paths  # rutas repo-relativas
from datetime import datetime, timezone
from typing import Optional

from pdb_ddp_client import DDPClient

# ── Journal entry ──
class JournalEntry:
    def __init__(self, ns: str, key: str, value: str, source: str = "local",
                 timestamp: str = None, clock: list = None):
        self.ns = ns
        self.key = key
        self.value = value
        self.source = source  # "local" | "cloud"
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        self.clock = clock or []  # Fase 2: vector clocks
    
    def to_dict(self):
        return {
            "key": self.key.encode().hex(),
            "value": self.value,
            "source": self.source,
            "updated_at": self.timestamp,
        }
    
    @staticmethod
    def from_entry(ns: str, entry: dict):
        key = bytes.fromhex(entry["key"]).decode() if isinstance(entry.get("key"), str) and len(entry["key"]) > 20 else entry.get("key", "")
        return JournalEntry(
            ns=ns,
            key=key,
            value=entry.get("value", ""),
            source=entry.get("source", "cloud"),
            timestamp=entry.get("updated_at"),
        )


class SyncEngine:
    """Motor de sincronización bidireccional con anti-bucle."""
    
    def __init__(self, ddp: DDPClient = None):
        self.ddp = ddp or DDPClient()
        self.journal = []  # WAL local
        self.last_sync = {}
        self.source = "local"  # Identidad de este nodo

    def _authz(self, ns: str, op: str):
        """Gate de macaroons (Fase 3). Con env DDP_MACAROON, el token debe
        autorizar el ns. Convención: pull/apply escribe local → op=write;
        push lee local → op=read. Sin token, authz desactivada."""
        token = os.environ.get("DDP_MACAROON", "")
        if not token:
            return True, "authz desactivada"
        try:
            from pdb_macaroon import check_access
            return check_access(token, ns, op)
        except Exception as e:
            return False, f"authz no disponible: {e}"
    
    # ── Journal (WAL) ──
    def write(self, ns: str, key: str, value: str) -> JournalEntry:
        """Escribir entrada en journal local con source=local.
        
        Esta entrada será replicada al cloud en el próximo sync.
        """
        entry = JournalEntry(ns, key, value, source=self.source)
        self.journal.append(entry)
        return entry
    
    # ── Push (local → cloud) ──
    def push_full_diff(self, ns: str, batch_size: int = 100) -> dict:
        """Push local→edge por DIFF de subkeys — LOCAL ES CANÓNICO.

        El journal (WAL) del SyncEngine nunca se alimenta en el flujo real
        (MVM/scripts/vm_api escriben directo a _globals) → push_pending devuelve
        applied=0 SIEMPRE y el edge queda desactualizado. Este método compara
        el contenido REAL del PDB local contra el edge y pushea lo que falta.
        Sin loops: el pull de vuelta se salta (timestamps embebidos / anti-bucle).
        """
        from pdb_tools import decode_subkey, encode_subkey

        # 1) Subkeys del edge (pull completo paginado, keyset)
        edge_keys = set()
        cursor, last_key = None, None
        for _ in range(200):  # safety: 200 páginas × 500 = 100k entries
            result = self.ddp.pull(ns, since=cursor or "1970-01-01", batch_size=500, last_key=last_key)
            if "error" in result:
                return {"error": f"pull edge: {result['error']}"}
            for e in result.get("entries", []):
                raw = e.get("key", "")
                if isinstance(raw, str) and raw and all(c in "0123456789abcdefABCDEF" for c in raw):
                    kb = bytes.fromhex(raw)
                else:
                    kb = str(raw).encode()
                try:
                    edge_keys.add(kb.decode())
                except UnicodeDecodeError:
                    try:
                        edge_keys.add("\x00".join(decode_subkey(kb)))
                    except Exception:
                        continue
            if not result.get("more"):
                break
            cursor = result.get("since", cursor)
            last_key = result.get("last_key")
            if not last_key:
                break

        # 2) Subkeys locales (SQL directo — misma máquina, instantáneo).
        #    Read-only + busy_timeout: el vm_api escribe constantemente y un
        #    SELECT largo puede chocar con el lock de escritura.
        import sqlite3
        from pathlib import Path as _Path
        db_path = os.environ.get(
            "PDB_PATH", str(_Path.home() / "pdb-data" / "lumen-pdb.db")
        )
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
        con.execute("PRAGMA busy_timeout = 15000")
        rows = con.execute("SELECT subkey, value FROM _globals WHERE ns = ?", (ns,)).fetchall()
        con.close()

        local_map = {}
        for sk_blob, value in rows:
            sk = bytes(sk_blob) if isinstance(sk_blob, (bytes, bytearray)) else str(sk_blob).encode()
            try:
                subs = decode_subkey(sk)
            except Exception:
                try:
                    subs = [sk.decode()]
                except Exception:
                    continue
            # Normalizar: subíndices numéricos (MUMPS) y values binarios
            subs = [str(s) for s in subs]
            if isinstance(value, (bytes, bytearray)):
                value = value.decode("utf-8", errors="replace")
            if subs:
                local_map["\x00".join(subs)] = (subs, value)

        # 3) Diff: lo que el edge NO tiene
        missing = sorted(set(local_map) - edge_keys)
        if not missing:
            return {"status": "ok", "applied": 0, "diff": 0, "edge": len(edge_keys), "local": len(local_map)}

        # 4) Push en lotes (el edge resuelve conflictos por timestamp)
        pushed = 0
        now_iso = datetime.now(timezone.utc).isoformat()
        for i in range(0, len(missing), batch_size):
            entries = []
            for norm in missing[i:i + batch_size]:
                subs, value = local_map[norm]
                entries.append({
                    "key": encode_subkey(subs).hex(),
                    "value": value,
                    "updated_at": now_iso,
                })
            result = self.ddp.push(ns, entries)
            if "error" in result:
                return {"error": f"push: {result['error']}", "applied": pushed}
            pushed += len(entries)
        return {"status": "ok", "applied": pushed, "diff": len(missing), "edge": len(edge_keys), "local": len(local_map)}

    # ── Push (local → cloud, journal) ──
    def push_pending(self, ns: str) -> dict:
        """Enviar entries locales pendientes al cloud.

        Incremental por cursor de seq: solo entries posteriores al último
        push confirmado. El cursor avanza únicamente si el push tuvo éxito,
        así un fallo de red reintenta el mismo tramo (at-least-once)."""
        ok, reason = self._authz(ns, "read")
        if not ok:
            return {"error": f"macaroon: {reason}"}
        from pdb_journal import read_after_cursor, cursor_set

        wal_entries = read_after_cursor("push", source="local", limit=100)
        if not wal_entries:
            return {"status": "ok", "applied": 0}

        # Convertir a formato DDP (hex key)
        ddp_entries = []
        for e in wal_entries:
            ddp_entries.append({
                "key": e["key"].encode().hex(),
                "value": json.dumps(e),
                "source": "local",
                "updated_at": e["ts"],
            })

        result = self.ddp.push(ns, ddp_entries)
        if "error" not in result:
            cursor_set("push", max(e["seq"] for e in wal_entries))
    def pull_and_apply(self, ns: str) -> dict:
        """Traer cambios del cloud y aplicarlos localmente (paginado keyset).

        Paginación compuesta (updated_at + subkey) — sin estancamiento cuando
        muchas rows comparten el mismo updated_at (imports masivos).
        Anti-bucle: ignora entries con source=local (vinieron de aquí).
        LOCAL ES CANÓNICO: solo se aplica lo que no existe localmente o lo que
        el cloud tiene ESTRICTAMENTE más nuevo (timestamp embebido en el valor).
        """
        ok, reason = self._authz(ns, "write")
        if not ok:
            return {"error": f"macaroon: {reason}"}

        from pdb_tools import tool_set, tool_get, decode_subkey

        total_applied = 0
        total_skipped = 0
        total_entries = 0
        cursor = self.last_sync.get(ns)
        last_key = None
        last_ts = None

        for _ in range(100):  # safety: 100 páginas
            result = self.ddp.pull(ns, since=cursor, batch_size=500, last_key=last_key)
            if "error" in result:
                return result

            entries = result.get("entries", [])
            total_entries += len(entries)

            for entry_data in entries:
                source = entry_data.get("source", "cloud")

                # ⚠️ Anti-bucle: si el entry vino de "local", lo saltamos
                if source == self.source:
                    total_skipped += 1
                    continue

                raw_key = entry_data.get("key", "")
                if isinstance(raw_key, str) and raw_key and all(c in '0123456789abcdefABCDEF' for c in raw_key):
                    key_bytes = bytes.fromhex(raw_key)
                else:
                    key_bytes = str(raw_key).encode()

                # La clave del wire puede ser un string utf-8 simple (SyncEngine)
                # o una subkey ya codificada con encode_subkey (full_sync)
                subs = None
                try:
                    subs = [key_bytes.decode()]
                except UnicodeDecodeError:
                    try:
                        subs = decode_subkey(key_bytes)
                    except Exception:
                        self._log(f"clave no decodificable: {str(raw_key)[:32]}")
                        total_skipped += 1
                        continue

                if not subs or (len(subs) == 1 and not subs[0]):
                    total_skipped += 1
                    continue

                # ── Aplicar localmente — LOCAL ES CANÓNICO (regla Gonzalo 14-08-2026): ──
                #   - local no existe  → aplicar (el cloud rellena huecos)
                #   - cloud ESTRICTAMENTE más nuevo (timestamp embebido) → aplicar
                #   - local existe y es igual/más nuevo (o sin timestamps) → saltar
                try:
                    val = entry_data.get("value", "")
                    # Extraer el valor real si viene envuelto en un entry de journal
                    actual_ns, actual_subs, actual_val = ns, subs, val
                    try:
                        parsed = json.loads(val)
                        if isinstance(parsed, dict) and "value" in parsed:
                            actual_val = parsed["value"]
                            actual_ns = parsed.get("ns", ns)
                            if parsed.get("key"):
                                actual_subs = [parsed["key"]]
                    except Exception:
                        parsed = None

                    def _ts_of(v):
                        if isinstance(v, dict):
                            for k in ("saved_at", "updated_at", "timestamp", "ts", "created_at"):
                                if k in v and isinstance(v[k], (int, float)):
                                    return v[k]
                        return None

                    def _as_dict(v):
                        if isinstance(v, dict):
                            return v
                        if isinstance(v, str):
                            try:
                                j = json.loads(v)
                                return j if isinstance(j, dict) else None
                            except Exception:
                                return None
                        return None

                    local_r = tool_get({"ns": actual_ns, "subs": actual_subs})
                    local_val = local_r.get("value") if local_r.get("success") else None
                    if local_val is not None:
                        lt = _ts_of(_as_dict(local_val))
                        it = _ts_of(parsed if isinstance(parsed, dict) else _as_dict(actual_val))
                        # El local manda: solo se aplica si el cloud es ESTRICTAMENTE más nuevo
                        if lt is None or it is None or it <= lt:
                            total_skipped += 1
                            continue

                    tool_set({"ns": actual_ns, "subs": actual_subs, "value": actual_val})
                    total_applied += 1
                except Exception as e:
                    self._log(f"Apply error: {e}")

            if not result.get("more"):
                break
            cursor = result.get("since", cursor)
            last_key = result.get("last_key")
            if not last_key:
                break  # sin cursor de keyset no avanzamos de forma segura

        if cursor:
            self.last_sync[ns] = cursor

        return {
            "entries": total_entries,
            "applied": total_applied,
            "skipped": total_skipped,
            "more": False,
        }
    
    # ── Sync completo ──
    def sync(self, ns: str) -> dict:
        """Sync bidireccional completo:
        1. Push cambios locales al cloud
        2. Pull cambios del cloud y aplicarlos
        """
        push_result = self.push_pending(ns)
        pull_result = self.pull_and_apply(ns)
        
        return {
            "push": push_result,
            "pull": pull_result,
            "name": "source tagging",
            "version": "0.1",
        }
    
    def _log(self, msg: str):
        print(f"[sync] {msg}")

    def _apply_entry(self, entry: JournalEntry):
        """Aplicar entry localmente.

        Por defecto: last-write-wins (sobrescribe).
        Sobrescribir para namespaces específicos.
        """
        pass  # Implementación específica por namespace


# ── Demo ──
if __name__ == "__main__":
    import sys
    
    engine = SyncEngine()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "demo"
    
    if cmd == "sync":
        ns = sys.argv[2] if len(sys.argv) > 2 else "pdb"
        print(json.dumps(engine.sync(ns), indent=2))
    elif cmd == "push":
        ns = sys.argv[2] if len(sys.argv) > 2 else "pdb"
        # Añadir entry local de prueba
        engine.write(ns, f"test:{int(time.time())}", "sync test")
        print(json.dumps(engine.push_pending(ns), indent=2))
    elif cmd == "pull":
        ns = sys.argv[2] if len(sys.argv) > 2 else "pdb"
        print(json.dumps(engine.pull_and_apply(ns), indent=2))
    else:
        print("Usage: sync|push|pull [namespace]")