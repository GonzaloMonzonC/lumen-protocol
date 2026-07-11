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
        pending = [e for e in self.journal if e.source == "local"]
        if not pending:
            return {"status": "ok", "applied": 0}
        
        entries = [e.to_dict() for e in pending]
        result = self.ddp.push(ns, entries)
        
        if "error" not in result:
            # Marcar como enviados (o limpiar)
            for e in pending:
                e.source = "synced"
        
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
            entry = JournalEntry.from_entry(ns, entry_data)
            
            # ⚠️ Anti-bucle: si el entry vino de "local", lo saltamos
            if entry.source == self.source:
                skipped += 1
                continue
            
            # Aplicar localmente (depende del namespace)
            self._apply_entry(entry)
            applied += 1
        
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
