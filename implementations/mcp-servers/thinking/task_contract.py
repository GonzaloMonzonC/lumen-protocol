"""task_contract.py — Contrato de tarea para colaboración multi-nodo.

Pieza 1 del mínimo viable (doc 07-colaboracion-multinodo):
sin contrato, dos Hermes "colaboran" pero no convergen.

Un contrato declara, ANTES de trabajar:
  - objetivo        qué hay que conseguir
  - entradas        qué recibe (rutas, referencias, datos)
  - salidas         qué debe producir
  - criterio        cómo se sabe que está bien (verificable)
  - límites         qué NO se puede tocar
  - rol             qué nodo puede reclamarla

Y el estado de la reclamación: quién la tiene, desde cuándo, hasta cuándo.

NO implementa locks con lease (pospuesto a fase 2 por Poli: "un lock sin
contención real es falsa seguridad"). Solo expone el contrato y el dueño
declarado, que es lo que hace falta para que dos nodos no trabajen el mismo
objetivo sin saberlo.
"""
from __future__ import annotations

import time
import uuid


# ── Estados válidos de una reclamación ────────────────────────────────────
CLAIM_FREE = "free"
CLAIM_CLAIMED = "claimed"
CLAIM_DONE = "done"
CLAIM_REJECTED = "rejected"


def _now() -> float:
    return time.time()


def build_contract(objective: str, inputs=None, outputs=None, criterion=None,
                   limits=None, role: str = "", author: str = "") -> dict:
    """Construye un contrato de tarea. Todos los campos salvo objetivo son opcionales."""
    return {
        "contract_id": f"ctr_{uuid.uuid4().hex[:12]}",
        "objective": str(objective or "").strip(),
        "inputs": list(inputs or []),
        "outputs": list(outputs or []),
        "criterion": str(criterion or "").strip(),   # cómo se verifica el éxito
        "limits": list(limits or []),                # qué NO se toca
        "role": str(role or ""),                     # qué nodo puede reclamarlo
        "author": str(author or ""),
        "created_at": _now(),
        # Estado de la reclamación
        "claim_status": CLAIM_FREE,
        "claimed_by": "",
        "claimed_at": None,
        # Traza (pieza 3): deja rastro de lo que pasó
        "history": [],
    }


def validate_contract(c: dict) -> tuple[bool, str]:
    """Un contrato sin objetivo o sin criterio no sirve: no se puede verificar."""
    if not c.get("objective"):
        return False, "falta 'objective': sin objetivo no hay tarea"
    if not c.get("criterion"):
        return False, ("falta 'criterion': sin criterio de éxito no se puede "
                       "decidir si está hecha (dos nodos 'colaborarían' sin converger)")
    return True, ""


def log_event(c: dict, kind: str, actor: str, detail: str = "") -> dict:
    """Añade un evento a la traza del contrato (correlation por contract_id)."""
    c.setdefault("history", []).append({
        "ts": _now(),
        "kind": kind,
        "actor": actor or "?",
        "detail": str(detail)[:500],
    })
    return c


def claim(c: dict, node: str) -> tuple[bool, str]:
    """Reclama el contrato. Rechaza si ya lo tiene otro nodo (no hay lease aún)."""
    if c.get("claim_status") == CLAIM_DONE:
        return False, "el contrato ya está cerrado (done)"
    owner = c.get("claimed_by") or ""
    if owner and owner != node:
        return False, f"ya lo tiene '{owner}' desde {_fmt(c.get('claimed_at'))}"
    c["claim_status"] = CLAIM_CLAIMED
    c["claimed_by"] = node
    c["claimed_at"] = c.get("claimed_at") or _now()
    log_event(c, "claim", node)
    return True, f"reclamado por {node}"


def release(c: dict, node: str, outcome: str = CLAIM_FREE,
            checkpoint: str = "") -> tuple[bool, str]:
    """Libera el contrato dejando checkpoint (pieza 2: handoff)."""
    if (c.get("claimed_by") or "") not in ("", node):
        return False, f"no eres el dueño ('{c.get('claimed_by')}')"
    c["claim_status"] = outcome if outcome in (CLAIM_DONE, CLAIM_REJECTED) else CLAIM_FREE
    if checkpoint:
        c.setdefault("checkpoints", []).append({
            "ts": _now(), "by": node, "note": str(checkpoint)[:1000],
        })
    log_event(c, "release:" + c["claim_status"], node, checkpoint)
    if c["claim_status"] != CLAIM_CLAIMED:
        c["claimed_by"] = ""
    return True, f"liberado ({c['claim_status']})"


def format_contract(c: dict) -> str:
    """Vista legible del contrato: la que se pone en el backoffice."""
    lines = [
        f"📋 CONTRATO {c.get('contract_id','?')}",
        f"   Objetivo : {c.get('objective') or '(sin definir)'}",
        f"   Criterio : {c.get('criterion') or '(SIN CRITERIO — no verificable)'}",
    ]
    if c.get("inputs"):
        lines.append(f"   Entradas : {', '.join(map(str, c['inputs']))}")
    if c.get("outputs"):
        lines.append(f"   Salidas  : {', '.join(map(str, c['outputs']))}")
    if c.get("limits"):
        lines.append(f"   Límites  : {', '.join(map(str, c['limits']))}")
    if c.get("role"):
        lines.append(f"   Rol      : {c['role']}")
    st = c.get("claim_status", CLAIM_FREE)
    owner = c.get("claimed_by") or "—"
    lines.append(f"   Estado   : {st} (dueño: {owner})")
    cp = c.get("checkpoints") or []
    if cp:
        last = cp[-1]
        lines.append(f"   Último checkpoint [{last['by']}]: {last['note'][:120]}")
    hist = c.get("history") or []
    if hist:
        lines.append(f"   Traza    : {len(hist)} eventos "
                     f"(último: {hist[-1]['kind']} por {hist[-1]['actor']})")
    return "\n".join(lines)


def _fmt(ts) -> str:
    if not ts:
        return "?"
    return time.strftime("%H:%M:%S", time.localtime(ts))


def _persist() -> None:
    """Persiste el estado de forma SÍNCRONA tras mutar un contrato.

    Por qué no basta _save_state(): lanza _pdb_save_all en un Thread daemon
    ("never block a handler"). Para un autosave periódico eso está bien, pero
    para una mutación de contrato es un fallo silencioso: el proceso puede
    terminar, el hilo puede no llegar a escribir, y el otro nodo NO ve el
    contrato. Comprobado 2026-10-19: llamando _pdb_save_all() directo el
    contrato aparece en disco; vía _save_state() no siempre.

    Un contrato es una operación puntual (no un autosave cada 10s), así que
    pagar ~decenas de ms aquí es correcto: la corrección vale más que la latencia.
    """
    try:
        import server as _srv
        _srv._pdb_save_all()          # síncrono: garantiza escritura
    except Exception as _e:
        try:
            import sys as _s
            _s.stderr.write(f"[lumen] contract persist: {_e}\n")
        except Exception:
            pass


# ── Handlers MCP ─────────────────────────────────────────────────────────

def tool_contract_create(args: dict) -> dict:
    c = build_contract(
        objective=args.get("objective", ""),
        inputs=args.get("inputs"),
        outputs=args.get("outputs"),
        criterion=args.get("criterion", ""),
        limits=args.get("limits"),
        role=args.get("role", ""),
        author=args.get("author", ""),
    )
    ok, why = validate_contract(c)
    if not ok:
        return {"content": [{"type": "text", "text": f"❌ Contrato rechazado: {why}"}],
                "contract": c, "valid": False}
    store = _store()
    store[c["contract_id"]] = c
    _persist()
    return {"content": [{"type": "text", "text": "✅ Contrato creado\n\n" + format_contract(c)}],
            "contract": c, "valid": True}


def tool_contract_get(args: dict) -> dict:
    c = _store().get(args.get("contract_id", ""))
    if not c:
        return {"content": [{"type": "text", "text": f"Contrato '{args.get('contract_id')}' no encontrado."}]}
    return {"content": [{"type": "text", "text": format_contract(c)}], "contract": c}


def tool_contract_claim(args: dict) -> dict:
    c = _store().get(args.get("contract_id", ""))
    if not c:
        return {"content": [{"type": "text", "text": "Contrato no encontrado."}]}
    ok, msg = claim(c, args.get("node", ""))
    if ok:
        _persist()
    return {"content": [{"type": "text", "text": ("✅ " if ok else "❌ ") + msg +
                         "\n\n" + format_contract(c)}], "ok": ok, "contract": c}


def tool_contract_handoff(args: dict) -> dict:
    c = _store().get(args.get("contract_id", ""))
    if not c:
        return {"content": [{"type": "text", "text": "Contrato no encontrado."}]}
    ok, msg = release(c, args.get("node", ""),
                      outcome=args.get("outcome", CLAIM_FREE),
                      checkpoint=args.get("checkpoint", ""))
    if ok:
        _persist()
    return {"content": [{"type": "text", "text": ("✅ " if ok else "❌ ") + msg +
                         "\n\n" + format_contract(c)}], "ok": ok, "contract": c}


def tool_contract_list(args: dict) -> dict:
    store = _store()
    if not store:
        return {"content": [{"type": "text", "text": "No hay contratos."}]}
    lines = [f"📋 {len(store)} contratos:"]
    for c in sorted(store.values(), key=lambda x: -x.get("created_at", 0)):
        owner = c.get("claimed_by") or "—"
        lines.append(f"   [{c.get('claim_status','?'):8}] {c.get('contract_id')} · "
                     f"{c.get('objective','')[:60]} · dueño: {owner}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}], "contracts": list(store.values())}


# ── Almacén (en memoria + PDB) ───────────────────────────────────────────

_CONTRACTS: dict = {}


def _store() -> dict:
    """Contratos en memoria. La persistencia en PDB es el siguiente paso."""
    return _CONTRACTS


CONTRACT_HANDLERS = {
    "contract_create": tool_contract_create,
    "contract_get": tool_contract_get,
    "contract_claim": tool_contract_claim,
    "contract_handoff": tool_contract_handoff,
    "contract_list": tool_contract_list,
}

CONTRACT_SCHEMAS = [
    {
        "name": "contract_create",
        "description": ("Crea un CONTRATO DE TAREA para colaboración entre nodos: objetivo, entradas, "
                        "salidas, criterio de éxito verificable y límites. Sin criterio no hay contrato: "
                        "sin él dos agentes 'colaboran' sin converger. [LUMEN]"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "objective": {"type": "string", "description": "Qué hay que conseguir"},
                "inputs": {"type": "array", "items": {"type": "string"}, "description": "Qué recibe (rutas, refs)"},
                "outputs": {"type": "array", "items": {"type": "string"}, "description": "Qué debe producir"},
                "criterion": {"type": "string", "description": "CÓMO se verifica el éxito (obligatorio)"},
                "limits": {"type": "array", "items": {"type": "string"}, "description": "Qué NO se puede tocar"},
                "role": {"type": "string", "description": "Qué nodo/rol puede reclamarlo"},
                "author": {"type": "string", "description": "Quién lo crea"},
            },
            "required": ["objective", "criterion"],
        },
    },
    {
        "name": "contract_get",
        "description": "Muestra un contrato de tarea con su estado, dueño y traza. [LUMEN]",
        "inputSchema": {"type": "object", "properties": {
            "contract_id": {"type": "string"}}, "required": ["contract_id"]},
    },
    {
        "name": "contract_claim",
        "description": ("Reclama un contrato para trabajarlo. Rechaza si ya lo tiene otro nodo. "
                        "Deja rastro en la traza. [LUMEN]"),
        "inputSchema": {"type": "object", "properties": {
            "contract_id": {"type": "string"},
            "node": {"type": "string", "description": "Identidad del nodo (p.ej. hermes-pc, hermes-asus)"},
        }, "required": ["contract_id", "node"]},
    },
    {
        "name": "contract_handoff",
        "description": ("Libera el contrato dejando CHECKPOINT (handoff): qué se hizo, qué queda, "
                        "dónde están los artefactos. Permite que otro nodo continúe. [LUMEN]"),
        "inputSchema": {"type": "object", "properties": {
            "contract_id": {"type": "string"},
            "node": {"type": "string"},
            "outcome": {"type": "string", "enum": ["free", "done", "rejected"],
                        "description": "free=disponible para otro, done=terminado, rejected=no viable"},
            "checkpoint": {"type": "string", "description": "Estado: hecho / pendiente / artefactos"},
        }, "required": ["contract_id", "node"]},
    },
    {
        "name": "contract_list",
        "description": "Lista los contratos con su estado y dueño. [LUMEN]",
        "inputSchema": {"type": "object", "properties": {}},
    },
]
