"""team_session.py — Sesión de Equipo: el "turno de guardia" multi-nodo.

Pieza 3 del mínimo viable (docs 07 y 08). NO es un sistema nuevo: es un
ENVOLTORIO del contrato de tarea de task_contract.py.

La regla que evita el error clásico (Smith):
    "La sesión es la VISTA. El contrato es la VERDAD."
    "Se rompe si la sesión se vuelve además el registro durable."

Por eso aquí NO se duplica el estado:
  - el dueño del turno ES contract.claimed_by   (no un campo aparte)
  - el checkpoint ES contract.history           (no un snapshot opaco)
  - el estado se DERIVA del contrato + dotación (no se almacena dos veces)

Lo único propio de la sesión:
  - dotacion[]  qué nodos participan (1..N)
  - objetivo    ya lo tiene el contrato
  - mando       quién tiene la palabra AHORA (puede haber varios nodos en la
                dotación y solo uno con el claim)

Estados (derivados, no almacenados como verdad paralela):
    corriendo        -> hay un claim activo
    esperando-humano -> el dueño soltó con outcome=free y hay checkpoint
    pausado          -> como esperando-humano pero con motivo explícito
    bloqueado        -> el dueño soltó con outcome=rejected
    cerrado          -> claim_status == done
    libre            -> sin claim y sin checkpoint
"""
from __future__ import annotations

import time
import uuid


# ── Estados de sesión (derivados) ─────────────────────────────────────────
ST_RUNNING = "corriendo"
ST_WAITING = "esperando-humano"
ST_PAUSED = "pausado"
ST_BLOCKED = "bloqueado"
ST_CLOSED = "cerrado"
ST_FREE = "libre"


def build_session(objective: str, members=None, criterion: str = "",
                  role: str = "", author: str = "") -> dict:
    """Crea una sesión de equipo envolviendo un contrato.

    members: lista de nodos que participan (1..N). El primero NO queda con el
    mando automáticamente: hay que reclamar (contract_claim).
    """
    from task_contract import build_contract

    members = [str(m) for m in (members or []) if str(m).strip()]
    contract = build_contract(
        objective=objective,
        criterion=criterion,
        role=role,
        author=author,
    )
    return {
        "session_id": f"ses_{uuid.uuid4().hex[:12]}",
        "contract": contract,        # ← LA VERDAD (no se duplica)
        "members": members or ["hermes"],
        "created_at": time.time(),
        "notes": [],
    }


def derive_state(s: dict) -> str:
    """Deriva el estado de la sesión DEL CONTRATO (nunca de un campo paralelo)."""
    c = s.get("contract") or {}
    status = c.get("claim_status")
    if status == "done":
        return ST_CLOSED
    if status == "rejected":
        return ST_BLOCKED
    if status == "claimed":
        return ST_RUNNING
    # libre: ¿hubo trabajo antes? Entonces espera a alguien.
    if c.get("checkpoints"):
        return ST_WAITING
    return ST_FREE


def current_owner(s: dict) -> str:
    """Quién tiene el mando: sale del contrato, no de la sesión."""
    return (s.get("contract") or {}).get("claimed_by") or ""


def format_session(s: dict) -> str:
    """Vista de línea de turnos: lo que se pinta en el backoffice."""
    c = s.get("contract") or {}
    st = derive_state(s)
    owner = current_owner(s) or "—"
    icon = {ST_RUNNING: "🟢", ST_WAITING: "🟡", ST_PAUSED: "🟠",
            ST_BLOCKED: "🔴", ST_CLOSED: "✅", ST_FREE: "⚪"}.get(st, "⚪")
    lines = [
        f"{icon} TURNO {s.get('session_id','?')} · {st.upper()}",
        f"   Objetivo : {c.get('objective') or '(sin definir)'}",
        f"   Mando    : {owner}",
        f"   Dotación : {', '.join(s.get('members') or [])}",
    ]
    if c.get("criterion"):
        lines.append(f"   Criterio : {c['criterion']}")
    cps = c.get("checkpoints") or []
    if cps:
        last = cps[-1]
        lines.append(f"   Checkpoint [{last.get('by','?')}]: {str(last.get('note',''))[:120]}")
    hist = c.get("history") or []
    if hist:
        lines.append(f"   Traza    : {len(hist)} eventos "
                     f"(último: {hist[-1].get('kind')} por {hist[-1].get('actor')})")
    return "\n".join(lines)


def add_member(s: dict, node: str) -> tuple[bool, str]:
    node = str(node or "").strip()
    if not node:
        return False, "nodo vacío"
    if node in (s.get("members") or []):
        return False, f"'{node}' ya está en la dotación"
    s.setdefault("members", []).append(node)
    _log(s, "member_add", node)
    return True, f"'{node}' añadido a la dotación"


def remove_member(s: dict, node: str) -> tuple[bool, str]:
    node = str(node or "").strip()
    members = s.get("members") or []
    if node not in members:
        return False, f"'{node}' no está en la dotación"
    if current_owner(s) == node:
        return False, (f"'{node}' tiene el mando: libera el contrato antes de "
                       f"sacarlo de la dotación")
    members.remove(node)
    _log(s, "member_remove", node)
    return True, f"'{node}' sacado de la dotación"


def _log(s: dict, kind: str, actor: str, detail: str = "") -> None:
    """Los eventos van a la traza del CONTRATO (una sola verdad)."""
    from task_contract import log_event
    log_event(s["contract"], kind, actor, detail)


# ── Handlers MCP ─────────────────────────────────────────────────────────

_SESSIONS: dict = {}


def _store() -> dict:
    return _SESSIONS


def _persist() -> None:
    """Persiste de forma SÍNCRONA (mismo motivo que en task_contract).

    Verificado 2026-10-19: _save_state() lanza el save en un hilo daemon, y para
    una mutación puntual eso es un fallo silencioso. _pdb_save_all() directo sí
    escribe.
    """
    try:
        import server as _srv
        _srv._pdb_save_all()
    except Exception as _e:
        try:
            import sys as _s
            _s.stderr.write(f"[lumen] session persist: {_e}\n")
        except Exception:
            pass


def _load_from_globals(globals_data: dict) -> int:
    """Carga las sesiones desde el estado persistido. Devuelve cuántas."""
    n = 0
    store = _store()
    for k, v in (globals_data or {}).items():
        if k.startswith("global:teamsession:") and isinstance(v, dict):
            store[k.split(":", 2)[2]] = v
            n += 1
    return n


def tool_session_open(args: dict) -> dict:
    s = build_session(
        objective=args.get("objective", ""),
        members=args.get("members"),
        criterion=args.get("criterion", ""),
        role=args.get("role", ""),
        author=args.get("author", ""),
    )
    from task_contract import validate_contract
    ok, why = validate_contract(s["contract"])
    if not ok:
        return {"content": [{"type": "text", "text": f"❌ Turno rechazado: {why}"}],
                "session": s, "valid": False}
    _store()[s["session_id"]] = s
    _persist()
    return {"content": [{"type": "text", "text": "✅ Turno abierto\n\n" + format_session(s)}],
            "session": s, "valid": True}


def tool_session_get(args: dict) -> dict:
    s = _store().get(args.get("session_id", ""))
    if not s:
        return {"content": [{"type": "text", "text": f"Turno '{args.get('session_id')}' no encontrado."}]}
    return {"content": [{"type": "text", "text": format_session(s)}], "session": s}


def tool_session_claim(args: dict) -> dict:
    """Tomar el mando. Delega en el contrato: la exclusión ya está probada allí."""
    from task_contract import claim
    s = _store().get(args.get("session_id", ""))
    if not s:
        return {"content": [{"type": "text", "text": "Turno no encontrado."}]}
    node = args.get("node", "")
    if node and node not in (s.get("members") or []):
        return {"content": [{"type": "text",
                             "text": f"❌ '{node}' no está en la dotación: añádelo antes de darle el mando."}],
                "ok": False}
    ok, msg = claim(s["contract"], node)
    if ok:
        _persist()
    return {"content": [{"type": "text", "text": ("✅ " if ok else "❌ ") + msg +
                         "\n\n" + format_session(s)}], "ok": ok, "session": s}


def tool_session_handoff(args: dict) -> dict:
    """Soltar el mando dejando checkpoint. Delega en el contrato."""
    from task_contract import release
    s = _store().get(args.get("session_id", ""))
    if not s:
        return {"content": [{"type": "text", "text": "Turno no encontrado."}]}
    ok, msg = release(s["contract"], args.get("node", ""),
                      outcome=args.get("outcome", "free"),
                      checkpoint=args.get("checkpoint", ""))
    if ok:
        _persist()
    return {"content": [{"type": "text", "text": ("✅ " if ok else "❌ ") + msg +
                         "\n\n" + format_session(s)}], "ok": ok, "session": s}


def tool_session_member(args: dict) -> dict:
    """Añade o saca un nodo de la dotación."""
    s = _store().get(args.get("session_id", ""))
    if not s:
        return {"content": [{"type": "text", "text": "Turno no encontrado."}]}
    action = args.get("action", "add")
    node = args.get("node", "")
    fn = add_member if action == "add" else remove_member
    ok, msg = fn(s, node)
    if ok:
        _persist()
    return {"content": [{"type": "text", "text": ("✅ " if ok else "❌ ") + msg +
                         "\n\n" + format_session(s)}], "ok": ok, "session": s}


def tool_session_list(args: dict) -> dict:
    """La LÍNEA DE TURNOS: lo que ve Gonzalo en el backoffice."""
    store = _store()
    if not store:
        return {"content": [{"type": "text", "text": "No hay turnos abiertos."}]}
    orden = {ST_RUNNING: 0, ST_WAITING: 1, ST_PAUSED: 1, ST_BLOCKED: 2, ST_FREE: 3, ST_CLOSED: 4}
    items = sorted(store.values(), key=lambda s: (orden.get(derive_state(s), 9),
                                                  -s.get("created_at", 0)))
    lines = [f"📋 LÍNEA DE TURNOS ({len(items)})"]
    for s in items:
        st = derive_state(s)
        icon = {ST_RUNNING: "🟢", ST_WAITING: "🟡", ST_PAUSED: "🟠",
                ST_BLOCKED: "🔴", ST_CLOSED: "✅", ST_FREE: "⚪"}.get(st, "⚪")
        c = s.get("contract") or {}
        d = " · ".join(s.get("members") or [])
        owner = current_owner(s) or "—"
        lines.append(f"   {icon} {st:16} {s.get('session_id')} · "
                     f"{str(c.get('objective',''))[:44]} · mando: {owner} · [{d}]")
    return {"content": [{"type": "text", "text": "\n".join(lines)}],
            "sessions": items}


SESSION_HANDLERS = {
    "team_open": tool_session_open,
    "team_get": tool_session_get,
    "team_claim": tool_session_claim,
    "team_handoff": tool_session_handoff,
    "team_member": tool_session_member,
    "team_list": tool_session_list,
}

SESSION_SCHEMAS = [
    {
        "name": "team_open",
        "description": ("Abre un TURNO DE EQUIPO: objetivo + dotación (1..N nodos) + criterio de éxito. "
                        "Es un envoltorio del contrato de tarea: el mando se toma con session_claim y se "
                        "suelta con session_handoff. Varios turnos = varios equipos trabajando a la vez. "
                        "[LUMEN]"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "objective": {"type": "string", "description": "Qué hay que conseguir en este turno"},
                "criterion": {"type": "string", "description": "Cómo se verifica (obligatorio)"},
                "members": {"type": "array", "items": {"type": "string"},
                            "description": "Nodos que participan, p.ej. ['hermes-pc','hermes-asus']"},
                "role": {"type": "string", "description": "Rol que puede reclamar el turno"},
                "author": {"type": "string", "description": "Quién abre el turno"},
            },
            "required": ["objective", "criterion"],
        },
    },
    {
        "name": "team_get",
        "description": "Muestra un turno: estado derivado, mando, dotación, checkpoint y traza. [LUMEN]",
        "inputSchema": {"type": "object", "properties": {
            "session_id": {"type": "string"}}, "required": ["session_id"]},
    },
    {
        "name": "team_claim",
        "description": ("Toma el mando del turno. Rechaza si otro nodo lo tiene (exclusión probada). "
                        "El nodo debe estar en la dotación. [LUMEN]"),
        "inputSchema": {"type": "object", "properties": {
            "session_id": {"type": "string"},
            "node": {"type": "string", "description": "Nodo que toma el mando"},
        }, "required": ["session_id", "node"]},
    },
    {
        "name": "team_handoff",
        "description": ("Suelta el mando dejando CHECKPOINT: qué se hizo, qué queda, dónde están los "
                        "artefactos. outcome=free deja el turno disponible (esperando-humano), done lo "
                        "cierra, rejected lo bloquea. [LUMEN]"),
        "inputSchema": {"type": "object", "properties": {
            "session_id": {"type": "string"},
            "node": {"type": "string"},
            "outcome": {"type": "string", "enum": ["free", "done", "rejected"]},
            "checkpoint": {"type": "string"},
        }, "required": ["session_id", "node"]},
    },
    {
        "name": "team_member",
        "description": "Añade (action=add) o saca (action=remove) un nodo de la dotación del turno. [LUMEN]",
        "inputSchema": {"type": "object", "properties": {
            "session_id": {"type": "string"},
            "node": {"type": "string"},
            "action": {"type": "string", "enum": ["add", "remove"], "default": "add"},
        }, "required": ["session_id", "node"]},
    },
    {
        "name": "team_list",
        "description": ("LÍNEA DE TURNOS: todos los turnos ordenados por estado (corriendo, esperándote, "
                        "bloqueado, libre, cerrado) con su mando y dotación. [LUMEN]"),
        "inputSchema": {"type": "object", "properties": {}},
    },
]
