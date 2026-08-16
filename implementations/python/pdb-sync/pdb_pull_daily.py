#!/usr/bin/env python3
"""pdb_pull_daily.py — Sincronización diaria EDGE → LOCAL de globals de AGENTES.

Decisión Gonzalo 14-08-2026:
  - Kanban y globals de agentes viven en LOCAL (VM-API) — canónicos.
  - 1 vez al día como máximo se hace pull desde PDB Edge (D1) para capturar
    cualquier cambio escrito en la nube (legacy/importera).
  - SOLO namespaces de agentes. NUNCA datos de sanidad/connectores
    (System, TRUST, HEALTH, PROCESSES, ...).

Uso:
  python pdb_pull_daily.py            # pull único (para cron diario)
  python pdb_pull_daily.py --dry-run  # solo inspecciona, no escribe local

Salida: vacía si no hay cambios (silencioso para cron watchdog);
solo imprime si hubo entries aplicados o errores.
"""
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

EDGE_URL = os.environ.get("PDB_EDGE_URL", "https://pdb-edge.WORKER_INTERNAL_URL")
LOCAL_URL = os.environ.get("PDB_LOCAL_URL", "http://localhost:8081")
CHECKPOINT_FILE = Path(os.environ.get(
    "PDB_PULL_CHECKPOINT",
    str(Path.home() / ".hermes" / "pdb-pull-checkpoint.json"),
))

# Globals de agentes que se replican edge→local (decidido 14-08-2026).
# NOTA: NO incluir sanidad/connectores (System, TRUST, HEALTH, PROCESSES, DMs).
AGENT_NS = ["KANBAN", "COLAB", "ROUTINE", "DECISIONS", "X_PUB", "X_STATE"]

BATCH = 500


def get_key() -> str:
    """DDP_HMAC_KEY: env → hermes .env → WLA .env."""
    k = os.environ.get("DDP_HMAC_KEY", "")
    if k:
        return k
    candidates = [
        Path(os.environ.get("HERMES_ENV", str(Path.home() / "AppData" / "Local" / "hermes" / ".env"))),
        Path(os.environ.get("WLA_ENV", str(Path.home() / "Documents" / "GitHub" / "ProjectOS" / "whatsapp-local-agent" / ".env"))),
    ]
    for p in candidates:
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("DDP_HMAC_KEY="):
                    return line.strip().split("=", 1)[1]
    return ""


def _sign(body_str: str, key: str):
    ts = str(int(time.time()))
    sig = hmac.new(key.encode(), (ts + body_str + key).encode(), hashlib.sha256).hexdigest()
    return ts, sig


def _post(url: str, body: dict, key: str, timeout: int = 60) -> dict:
    body_str = json.dumps(body, ensure_ascii=False)
    ts, sig = _sign(body_str, key)
    req = urllib.request.Request(
        url,
        data=body_str.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-DDP-Timestamp": ts,
            "X-DDP-HMAC": sig,
            "User-Agent": "Mozilla/5.0 pdb-pull-daily/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def pull_ns(ns: str, since: str, key: str) -> list:
    """Paginado por /ddp/sync. Devuelve lista de entries {key, value, updated_at}."""
    entries = []
    cursor = since
    for _ in range(50):  # safety: máx 50 páginas = 25k entries
        r = _post(f"{EDGE_URL}/ddp/sync", {"ns": ns, "since": cursor, "batch_size": BATCH}, key)
        if "error" in r:
            raise RuntimeError(f"edge sync {ns}: {r['error']}")
        batch = r.get("entries", [])
        entries.extend(batch)
        if not r.get("more"):
            break
        cursor = r.get("since", cursor)
    return entries


def push_local(ns: str, entries: list, key: str) -> dict:
    body = {"ns": ns, "entries": entries}
    return _post(f"{LOCAL_URL}/ddp/push", body, key, timeout=90)


def main() -> int:
    dry = "--dry-run" in sys.argv
    key = get_key()
    if not key:
        print("ERROR: DDP_HMAC_KEY no encontrada", flush=True)
        return 1

    cp = {}
    if CHECKPOINT_FILE.exists():
        try:
            cp = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        except Exception:
            cp = {}

    total_applied = 0
    errors = []
    for ns in AGENT_NS:
        since = cp.get(ns, "1970-01-01")
        try:
            entries = pull_ns(ns, since, key)
        except Exception as e:
            errors.append(f"{ns}: {e}")
            continue
        if not entries:
            continue
        if dry:
            print(f"[dry] {ns}: {len(entries)} entries pendientes (desde {since})")
            continue
        # Push local en lotes de 200
        for i in range(0, len(entries), 200):
            chunk = entries[i : i + 200]
            r = push_local(ns, chunk, key)
            if "error" in r:
                errors.append(f"{ns} push: {r['error']}")
                break
        cp[ns] = max(e.get("updated_at", since) for e in entries)
        total_applied += len(entries)
        print(f"✔ {ns}: {len(entries)} entries → local")

    if cp != json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8")) if CHECKPOINT_FILE.exists() else True:
        CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
        CHECKPOINT_FILE.write_text(json.dumps(cp, indent=2), encoding="utf-8")

    if errors:
        print("ERRORES: " + "; ".join(errors), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
