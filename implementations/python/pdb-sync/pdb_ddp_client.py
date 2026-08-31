#!/usr/bin/env python3
"""pdb_ddp_client.py — Cliente DDP-LUMEN v0.2 para el Cloud Bridge (pdb-edge worker).

Protocolo: https://github.com/GonzaloMonzonC/PRIVATE_REPO (src/ddp-routes.ts)
  GET  /ddp/health  (público)        → {ok, agent, version, hmac}
  GET  /ddp/schema  (público)        → {version, namespaces}
  GET  /ddp/status  (HMAC)           → {last_sync, pending, lag_ms, entries, namespaces}
  POST /ddp/sync    (HMAC)           → {entries, checksum, more, since}
  POST /ddp/push    (HMAC)           → {status, conflicts}
  POST /ddp/bulk-push (HMAC)         → full-sync sin resolución de conflictos

HMAC: HMAC-SHA256(ts + raw_body + key) — POST firma el body EXACTO enviado;
      GET firma ts + "" + key. Headers: X-DDP-Timestamp, X-DDP-HMAC.

Uso:
    from pdb_ddp_client import DDPClient
    client = DDPClient()
    client.health()                        # estado del bridge
    client.pull("KANBAN", since="2026-08-01T00:00:00Z", batch_size=500)
    client.push("COLAB", [{"key": hex_subkey, "value": "{}", "updated_at": "..."}])
"""
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


def _load_secrets_env() -> dict:
    """Lee ~/.hermes/secrets.env (y hermes/.env) como fallback de entorno.

    Los cron jobs no_agent corren sin el entorno de Hermes cargado; este
    archivo centraliza URL del edge + DDP_HMAC_KEY del ecosistema.
    """
    out = {}
    paths = [
        Path.home() / ".hermes" / "secrets.env",
        Path(os.environ.get("HERMES_ENV", str(Path.home() / "AppData" / "Local" / "hermes" / ".env"))),
    ]
    for p in paths:
        if p.exists():
            try:
                for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        out.setdefault(k.strip(), v.strip())
            except OSError:
                continue
    return out


def _default_key() -> str:
    """DDP_HMAC_KEY: env → secrets.env/hermes .env → WLA .env (misma clave compartida del ecosistema)."""
    k = os.environ.get("DDP_HMAC_KEY", "")
    if k:
        return k
    for p in [
        Path(os.environ.get("HERMES_ENV", str(Path.home() / "AppData" / "Local" / "hermes" / ".env"))),
        Path.home() / ".hermes" / "secrets.env",
        Path(os.environ.get("WLA_ENV", str(Path.home() / "Documents" / "GitHub" / "ProjectOS" / "whatsapp-local-agent" / ".env"))),
    ]:
        if p.exists():
            try:
                for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("DDP_HMAC_KEY="):
                        return line.strip().split("=", 1)[1]
            except OSError:
                continue
    return ""


class DDPError(RuntimeError):
    """Error de protocolo DDP (HTTP no-2xx o error en payload)."""


class DDPClient:
    """Cliente DDP-LUMEN v0.2 → pdb-edge worker (Cloud Bridge)."""

    def __init__(self, base_url: str | None = None, key: str | None = None, timeout: int = 60):
        secrets = _load_secrets_env()
        self.base_url = (
            base_url
            or os.environ.get("PDB_EDGE_URL")
            or secrets.get("PDB_EDGE_URL")
            or "https://pdb-edge.gonzalomonzonc.workers.dev"
        ).rstrip("/")
        self.key = key if key is not None else (os.environ.get("DDP_HMAC_KEY") or _default_key())
        self.timeout = timeout

    # ── Firmado ──────────────────────────────────────────────────────
    def _sign(self, raw_body: str) -> tuple[str, str]:
        ts = str(int(time.time()))
        sig = hmac.new(
            self.key.encode(), (ts + raw_body + self.key).encode(), hashlib.sha256
        ).hexdigest()
        return ts, sig

    def _headers(self, raw_body: str) -> dict:
        ts, sig = self._sign(raw_body)
        return {
            "Content-Type": "application/json",
            "X-DDP-Timestamp": ts,
            "X-DDP-HMAC": sig,
            "User-Agent": "Mozilla/5.0 DDPClient/0.2",
        }

    # ── Transporte ───────────────────────────────────────────────────
    def _get(self, path: str) -> dict:
        ts, sig = self._sign("")
        req = urllib.request.Request(
            self.base_url + path,
            headers={"X-DDP-Timestamp": ts, "X-DDP-HMAC": sig, "User-Agent": "Mozilla/5.0 DDPClient/0.2"},
        )
        return self._read(req)

    def _post(self, path: str, body: dict) -> dict:
        raw = json.dumps(body, ensure_ascii=False)
        req = urllib.request.Request(
            self.base_url + path, data=raw.encode("utf-8"), headers=self._headers(raw)
        )
        return self._read(req)

    def _read(self, req) -> dict:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            raise DDPError(f"HTTP {e.code} en {req.full_url}: {detail}") from e

    # ── API ──────────────────────────────────────────────────────────
    def health(self) -> dict:
        """Estado del bridge (público)."""
        return self._get("/ddp/health")

    def schema(self) -> dict:
        """Namespaces disponibles en el bridge (público)."""
        return self._get("/ddp/schema")

    def status(self) -> dict:
        """Estado de sync del bridge (HMAC)."""
        return self._get("/ddp/status")

    def pull(self, ns: str, since: str | None = None, batch_size: int = 500, last_key: str | None = None) -> dict:
        """Pull incremental de un namespace desde `since` (POST /ddp/sync).

        Keyset pagination: pasar `last_key` (hex de la última subkey) cuando
        `more=True` — evita el estancamiento cuando muchas rows comparten el
        mismo updated_at (imports masivos).

        Devuelve {entries: [{key(hex), value, updated_at}], checksum, more, since, last_key}.
        """
        if not self.key:
            raise DDPError("DDP_HMAC_KEY no configurada (DDPClient)")
        body = {"ns": ns, "since": since or "1970-01-01", "batch_size": batch_size}
        if last_key:
            body["last_key"] = last_key
        return self._post("/ddp/sync", body)

    def pull_all(self, ns: str, since: str | None = None, batch_size: int = 500) -> list[dict]:
        """Pull paginado completo de un namespace (keyset: timestamp + subkey)."""
        entries: list[dict] = []
        cursor = since or "1970-01-01"
        last_key = None
        for _ in range(100):  # safety: 100 páginas
            r = self.pull(ns, since=cursor, batch_size=batch_size, last_key=last_key)
            if "error" in r:
                raise DDPError(f"pull {ns}: {r['error']}")
            batch = r.get("entries", [])
            entries.extend(batch)
            if not r.get("more"):
                break
            cursor = r.get("since", cursor)
            last_key = r.get("last_key")
            if not last_key:
                break  # sin cursor de keyset, no podemos avanzar de forma segura
        return entries

    def push(self, ns: str, entries: list[dict]) -> dict:
        """Push de entries al bridge con resolución de conflictos por timestamp."""
        if not self.key:
            raise DDPError("DDP_HMAC_KEY no configurada (DDPClient)")
        return self._post("/ddp/push", {"ns": ns, "entries": entries})

    def bulk_push(self, ns: str, entries: list[dict]) -> dict:
        """Full-sync inicial (sin resolución de conflictos)."""
        if not self.key:
            raise DDPError("DDP_HMAC_KEY no configurada (DDPClient)")
        return self._post("/ddp/bulk-push", {"ns": ns, "entries": entries})


if __name__ == "__main__":
    # Smoke test contra el bridge real
    c = DDPClient()
    print("health:", c.health())
    print("schema:", c.schema())
    try:
        st = c.status()
        print("status:", st)
    except DDPError as e:
        print("status ERROR:", e)
    try:
        r = c.pull("KANBAN", since="2026-01-01", batch_size=5)
        print("pull KANBAN:", len(r.get("entries", [])), "entries, more =", r.get("more"))
        if r.get("entries"):
            print("  ejemplo:", json.dumps(r["entries"][0])[:200])
    except DDPError as e:
        print("pull ERROR:", e)
