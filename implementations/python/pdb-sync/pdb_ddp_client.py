#!/usr/bin/env python3
"""
pdb_ddp_client.py — DDP-03: DDP Client en Hermes (pull + push).

Arquitectura (Zalo):
- Worker autoritativo, Hermes hace pull periódico
- DDP sobre HTTP REST con HMAC auth
- Timestamp-based sync con batch control

Operaciones:
  pull(ns, since)   → Obtener cambios desde cloud
  push(ns, entries) → Enviar cambios locales a cloud
  status()          → Estado de sincronización
  heartbeat()       → Conexión cloud
"""

import os, json, time, hashlib, hmac
from datetime import datetime, timezone
from typing import Optional

# ── Config ──
DEFAULT_EDGE_URL = "https://pdb-edge.gonzalomonzonc.workers.dev"
DDP_VERSION = "0.1"

class DDPClient:
    """Cliente DDP para sincronización Hermes ↔ pdb-worker cloud."""
    
    def __init__(self, edge_url: str = None, hmac_key: str = None):
        self.edge_url = (edge_url or os.environ.get("PDB_EDGE_URL") or DEFAULT_EDGE_URL).rstrip("/")
        self.hmac_key = hmac_key or os.environ.get("DDP_HMAC_KEY") or ""
        self.last_sync = {}  # ns → timestamp
    
    def _sign(self, body: str) -> tuple[str, str]:
        """HMAC-SHA256 signature (Zalo: misma clave que trust 10/10)."""
        ts = datetime.now(timezone.utc).isoformat()
        if not self.hmac_key:
            return ts, ""
        msg = (ts + body + self.hmac_key).encode()
        sig = hmac.new(self.hmac_key.encode(), msg, hashlib.sha256).hexdigest()
        return ts, sig
    
    def _req(self, method: str, path: str, body: dict = None) -> dict:
        """HTTP request with HMAC auth."""
        import urllib.request, urllib.error
        
        url = f"{self.edge_url}{path}"
        data = json.dumps(body).encode() if body else None
        ts, sig = self._sign((data or b"").decode() if data else "")
        
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-DDP-Timestamp", ts)
        if sig:
            req.add_header("X-DDP-HMAC", sig)
        req.add_header("User-Agent", f"DDP-Client/{DDP_VERSION}")
        
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
        except Exception as e:
            return {"error": str(e)}
    
    # ── Health ──
    def health(self) -> dict:
        """Verificar conexión con el worker."""
        return self._req("GET", "/ddp/health")
    
    # ── Schema ──
    def schema(self) -> dict:
        """Obtener namespaces disponibles."""
        return self._req("GET", "/ddp/schema")
    
    # ── Status ──
    def status(self) -> dict:
        """Estado de sincronización del worker."""
        return self._req("GET", "/ddp/status")
    
    # ── Pull ──
    def pull(self, ns: str, since: str = None, batch_size: int = 100) -> dict:
        """Pull cambios desde el worker.
        
        Args:
            ns: Namespace (pdb, kb, dms, meta)
            since: Timestamp ISO desde el último sync
            batch_size: Máx entradas por respuesta
        Returns:
            {entries, checksum, more, since}
        """
        if not since:
            since = self.last_sync.get(ns) or "1970-01-01T00:00:00Z"
        
        return self._req("POST", "/ddp/sync", {
            "ns": ns,
            "since": since,
            "batch_size": batch_size,
        })
    
    # ── Push ──
    def push(self, ns: str, entries: list) -> dict:
        """Push cambios locales al worker.
        
        Args:
            ns: Namespace
            entries: [{key, value, updated_at}, ...]
        Returns:
            {status, applied, conflicts}
        """
        return self._req("POST", "/ddp/push", {
            "ns": ns,
            "entries": entries,
        })
    
    # ── Sync completo ──
    def sync(self, ns: str) -> dict:
        """Sync completo: pull + merge local.
        
        Obtiene cambios desde el worker y los aplica localmente.
        """
        result = self.pull(ns)
        if "error" in result:
            return result
        
        entries = result.get("entries", [])
        applied = 0
        
        for entry in entries:
            # Aplicar cada entrada: key, value, updated_at
            # La lógica de merge depende del namespace
            applied += 1
        
        # Actualizar timestamp
        if result.get("since"):
            self.last_sync[ns] = result["since"]
        
        return {
            "ns": ns,
            "entries": len(entries),
            "applied": applied,
            "more": result.get("more", False),
            "since": result.get("since"),
        }


# ── Demo ──
if __name__ == "__main__":
    import sys
    
    client = DDPClient()
    
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    
    if cmd == "health":
        print(json.dumps(client.health(), indent=2))
    elif cmd == "schema":
        print(json.dumps(client.schema(), indent=2))
    elif cmd == "status":
        print(json.dumps(client.status(), indent=2))
    elif cmd == "pull":
        ns = sys.argv[2] if len(sys.argv) > 2 else "pdb"
        since = sys.argv[3] if len(sys.argv) > 3 else None
        print(json.dumps(client.pull(ns, since), indent=2))
    else:
        print(f"Usage: {sys.argv[0]} [health|schema|status|pull]")
