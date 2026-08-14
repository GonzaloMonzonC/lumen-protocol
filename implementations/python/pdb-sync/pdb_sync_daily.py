#!/usr/bin/env python3
"""pdb_sync_daily.py — Sync DDP diario EDGE ↔ LOCAL (máximo 1 vez al día, vía cron).

Decisión Gonzalo 14-08-2026:
  - Los globals de agentes configurados se sincronizan por DDP entre el PDB local
    (VM-API) y el PDB Edge (Cloud Bridge, pdb-edge worker).
  - Kanban y datos de agentes viven en LOCAL (canónico); el pull diario captura
    cualquier cambio escrito en la nube (importeras/legacy).
  - NUNCA se sincronizan datos de sanidad/connectores
    (System, TRUST, HEALTH, PROCESSES, DMs, ...).

Namespaces de agentes configurados (editar AGENT_NS para añadir/quitar):
  KANBAN, COLAB, ROUTINE, DECISIONS, X_PUB, X_STATE

Protocolo: DDP-LUMEN v0.2 (HMAC-SHA256 ts+raw_body+key, conflictos por timestamp,
anti-bucle por source tagging). Cliente: pdb_ddp_client.py, motor: pdb_sync_engine.py.

Salida (para cron watchdog):
  - vacía        → OK, nada que reportar
  - resumen      → hubo entries sincronizados
  - error+exit 1 → fallo, alerta
"""
import json
import os
import sys
from pathlib import Path

import _paths  # noqa: F401  # sys.path del stack PDB
from pdb_sync_engine import SyncEngine

# Globals de agentes que se replican (configurados por Gonzalo, 14-08-2026)
AGENT_NS = ["KANBAN", "COLAB", "ROUTINE", "DECISIONS", "X_PUB", "X_STATE"]

CHECKPOINT = Path(os.environ.get(
    "PDB_SYNC_CHECKPOINT",
    str(Path.home() / ".hermes" / "pdb-sync-daily-checkpoint.json"),
))

MAX_PAGES = 60  # 60 × 500 = 30k entries por ns — safety


def main() -> int:
    dry = "--dry-run" in sys.argv
    engine = SyncEngine()
    if CHECKPOINT.exists():
        try:
            engine.last_sync = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        except Exception:
            engine.last_sync = {}

    report = []
    errors = []
    for ns in AGENT_NS:
        try:
            # 1) LOCAL → EDGE: journal local pendiente
            push = engine.push_pending(ns)
            if isinstance(push, dict) and "error" in push:
                errors.append(f"{ns} push: {push['error']}")
                continue
            pushed = push.get("applied", 0)

            # 2) EDGE → LOCAL: pull incremental paginado
            applied_total = 0
            pages = 0
            while pages < MAX_PAGES:
                r = engine.pull_and_apply(ns)
                if isinstance(r, dict) and "error" in r:
                    errors.append(f"{ns} pull: {r['error']}")
                    break
                applied_total += r.get("applied", 0)
                pages += 1
                if not r.get("more"):
                    break
            if dry:
                report.append(f"[dry] {ns}: pendiente de aplicar (push {pushed}, pull {applied_total})")
            elif pushed or applied_total:
                report.append(f"✔ {ns}: push {pushed}, pull {applied_total}")
        except Exception as e:
            errors.append(f"{ns}: {e}")

    if not dry:
        CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
        CHECKPOINT.write_text(json.dumps(engine.last_sync, indent=2), encoding="utf-8")

    if errors:
        print("ERRORES: " + "; ".join(errors), flush=True)
        return 1
    if report:
        print("Sync DDP diario:", flush=True)
        for line in report:
            print(line, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
