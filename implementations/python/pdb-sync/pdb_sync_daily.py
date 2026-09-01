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
import time
from pathlib import Path

import _paths  # noqa: F401  # sys.path del stack PDB
from pdb_sync_engine import SyncEngine

# Globals de agentes que se replican (configurados por Gonzalo, 14-08-2026)
AGENT_NS = ["KANBAN", "COLAB", "ROUTINE", "DECISIONS", "X_PUB", "X_STATE", "PRODUCT"]

CHECKPOINT = Path(os.environ.get(
    "PDB_SYNC_CHECKPOINT",
    str(Path.home() / ".hermes" / "pdb-sync-daily-checkpoint.json"),
))

MAX_PAGES = 60  # 60 × 500 = 30k entries por ns — safety


def reindex_kanban():
    """Recomputar ^KANBAN(meta) desde los datos REALES del PDB local.

    El meta es un resumen derivado — tras cada pull debe reflejar el estado real
    (nº tareas, niches, status, prioridades, saved_at=now), no valores stale.
    LOCAL ES CANÓNICO.
    """
    try:
        from pdb_tools import tool_order, tool_get, tool_set
        import re as _re

        def children(ns, prefix):
            key = ""
            out = []
            for _ in range(3000):
                r = tool_order({"ns": ns, "subs": prefix + [key], "direction": 1})
                if not r.get("success") or not r.get("value"):
                    break
                key = r["value"]
                out.append(key)
            return out

        tasks = children("KANBAN", ["task"])
        task_ids = []
        for t in tasks:
            m = _re.match(r"task_(\d+)$", t.strip())
            if m:
                task_ids.append(int(m.group(1)))
        task_ids = sorted(set(task_ids))

        niches = set()
        for nk in children("KANBAN", ["niche"]):
            m = _re.match(r"niche_(\d+)$", nk.strip())
            if m:
                niches.add(m.group(1))

        statuses = {"backlog": 0, "in_progress": 0, "done": 0}
        prios = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for tid in task_ids:
            st = (tool_get({"ns": "KANBAN", "subs": ["task", f"task_{tid}", "status"]}).get("value") or "").strip('"')
            pr = (tool_get({"ns": "KANBAN", "subs": ["task", f"task_{tid}", "priority"]}).get("value") or "").strip('"')
            statuses[st] = statuses.get(st, 0) + 1
            prios[pr] = prios.get(pr, 0) + 1

        total = len(task_ids)
        meta = {
            "total": total,
            "niches": len(niches),
            "done": statuses["done"],
            "backlog": statuses["backlog"],
            "in_progress": statuses["in_progress"],
            "critical": prios["critical"],
            "high": prios["high"],
            "medium": prios["medium"],
            "low": prios["low"],
            "saved_at": time.time(),
        }
        tool_set({"ns": "KANBAN", "subs": ["meta"], "value": json.dumps(meta)})
        return meta
    except Exception as e:
        return {"error": str(e)}


def _log_run(entry: dict):
    """Registro de invocaciones (forense: detectar ejecuciones fuera de horario)."""
    try:
        log = Path.home() / ".hermes" / "pdb-sync-runs.jsonl"
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def main() -> int:
    dry = "--dry-run" in sys.argv
    _log_run({"ts": time.time(), "event": "start", "argv": sys.argv})
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
            # 1) LOCAL → EDGE: push por DIFF real (el journal WAL nunca se alimenta
            #    en el flujo real → push_pending devolvía applied=0 siempre)
            push = engine.push_full_diff(ns)
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

    # Tras el pull, el meta del kanban debe reflejar la realidad local (canónico)
    if not dry:
        meta = reindex_kanban()
        if isinstance(meta, dict) and "error" not in meta:
            report.append(f"↻ KANBAN meta reindexado: {meta.get('total')} tareas, {meta.get('niches')} niches")
        elif isinstance(meta, dict):
            report.append(f"⚠ reindex kanban: {meta.get('error')}")

    if errors:
        _log_run({"ts": time.time(), "event": "end", "ok": False, "errors": errors})
        print("ERRORES: " + "; ".join(errors), flush=True)
        return 1
    _log_run({"ts": time.time(), "event": "end", "ok": True})
    if report:
        print("Sync DDP diario:", flush=True)
        for line in report:
            print(line, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
