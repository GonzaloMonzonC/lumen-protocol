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
    
    # ── Journal (WAL) ──
    def write(self, ns: str, key: str, value: str) -> JournalEntry:
        """Escribir entrada en journal local con source=local.
        
        Esta entrada será replicada al cloud en el próximo sync.
        """
        entry = JournalEntry(ns, key, value, source=self.source)
        self.journal.append(entry)
        return entry
    
    # ── Push (local → cloud) ──
    def push_pending(self, ns: str) -> dict:
        """Enviar entries locales pendientes al cloud."""
        from pdb_journal import read, write, make_entry, pending as wal_pending

        # Push entries del WAL con source=local
        wal_entries = read(source="local", limit=100)
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
        return result
    
    # ── Pull (cloud → local) ──
    def pull_and_apply(self, ns: str) -> dict:
        """Traer cambios del cloud y aplicarlos localmente.
        
        Anti-bucle: ignora entries con source=local (vinieron de aquí).
        """
        result = self.ddp.pull(ns, since=self.last_sync.get(ns))
        if "error" in result:
            return result
        
        entries = result.get("entries", [])
        applied = 0
        skipped = 0
        
        for entry_data in entries:
            key_bytes = bytes.fromhex(entry_data["key"]) if isinstance(entry_data.get("key"), str) and all(c in '0123456789abcdefABCDEF' for c in entry_data["key"]) else entry_data.get("key", "").encode()
            key = key_bytes.decode() if isinstance(key_bytes, bytes) else key_bytes
            
            source = entry_data.get("source", "cloud")
            
            # ⚠️ Anti-bucle: si el entry vino de "local", lo saltamos
            if source == self.source:
                skipped += 1
                continue
            
            # Aplicar localmente
            try:
                import sys, os
                sp = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
                if sp not in sys.path: sys.path.insert(0, sp)
                from pdb_tools import tool_set
                val = entry_data.get("value", "")
                # Extraer el valor real del entry del journal
                try:
                    parsed = json.loads(val)
                    actual_val = parsed.get("value", val) if isinstance(parsed, dict) else val
                    actual_ns = parsed.get("ns", ns) if isinstance(parsed, dict) else ns
                    actual_key = parsed.get("key", key) if isinstance(parsed, dict) else key
                except:
                    actual_val = val
                    actual_ns = ns
                    actual_key = key
                
                tool_set({"ns": actual_ns, "subs": [actual_key], "value": actual_val})
                applied += 1
            except Exception as e:
                self._log(f"Apply error: {e}")
        
        if result.get("since"):
            self.last_sync[ns] = result["since"]
        
        return {
            "entries": len(entries),
            "applied": applied,
            "skipped": skipped,
            "more": result.get("more", False),
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
