#!/usr/bin/env python3
"""MCP server for Poli — el agente MVM polimórfico.

Expone las rutinas Poli (PERSONALITY, THINKING, WIKI, DECISIONS, MEMORY, UTILS)
como herramientas MCP para que Hermes las invoque conversacionalmente. Mantiene
estado de sesión persistente entre invocaciones.
"""
from __future__ import annotations
import json, logging, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pdb"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lumen_mlight import execute as ml_execute
from poli_gateway import llm_call, MODELS

if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger(__name__)

# ── Ruta base de Poli ────────────────────────────────────────────────────────
_POLI_CORE = Path(os.environ.get("POLI_CORE", r"C:\Users\gonzalo\Documents\GitHub\poli\src\core"))

# ── Cargar rutinas M una vez ─────────────────────────────────────────────────
def _load_routines() -> dict[str, str]:
    routines = {}
    for mac in _POLI_CORE.glob("*.mac"):
        name = mac.stem.upper()  # PERSONALITY, UTILS, etc.
        routines[name] = mac.read_text(encoding="utf-8")
    return routines

_ROUTINES = _load_routines()

# ── Estado de sesión ─────────────────────────────────────────────────────────
class PoliState:
    """Mantiene el estado global Poli entre invocaciones.
    
    Los ^GLOBALES viven en un dict que se pasa como seed en cada ejecución.
    """
    def __init__(self):
        self.globals: list[dict] = []          # ^GLOBALES persistentes
        self.default_session = "hermes"
    
    def _globals_dict(self) -> dict:
        """Convierte self.globals a dict para inspección."""
        g = {}
        for entry in self.globals:
            ns = entry.get("ns", "")
            subs = entry.get("subs") or []
            # Construir clave plana para el log
            key = f"^{ns}({','.join(str(s) for s in subs)})" if subs else f"^{ns}"
            g[key] = entry.get("value")
        return g
    
    def seed(self) -> dict:
        """Ejecuta SEED para cargar modos por defecto si no existen,
        luego overrides: critic → deepseek v4 flash.
        """
        r = ml_execute(
            source='D SEED^PERSONALITY S ^PERSONALITY("critic","provider")="deepseek" S ^PERSONALITY("critic","model")="deepseek-v4-flash"',
            routines=_ROUTINES,
            globals_=self.globals,
            gas_limit=60000,
        )
        if r.get("ok"):
            self.globals = r.get("globals") or []
        return {"ok": r.get("ok"), "error": r.get("state", {}).get("error", {})}
    
    def exec(self, source: str, gas: int = 20000) -> dict:
        """Ejecuta código M arbitrario sobre el estado actual (con LLM nativo)."""
        r = ml_execute(
            source=source,
            routines=_ROUTINES,
            globals_=self.globals,
            gas_limit=gas,
            llm_api_keys=_LLM_KEYS,
        )
        if r.get("ok"):
            self.globals = r.get("globals") or []
        return r

# ── Instancia única ──────────────────────────────────────────────────────────
_STATE = PoliState()

# ── API keys para LLM nativo ──────────────────────────────────────────────────
def _load_llm_keys() -> dict[str, str]:
    keys = {}
    env_path = Path.home() / "AppData/Local/hermes/.env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k == "OPENROUTER_API_KEY": keys["openrouter"] = v
                elif k == "DEEPSEEK_API_KEY": keys["deepseek"] = v
    import os as _os
    if not keys.get("openrouter"):
        val = _os.environ.get("OPENROUTER_API_KEY")
        if val: keys["openrouter"] = val
    if not keys.get("deepseek"):
        val = _os.environ.get("DEEPSEEK_API_KEY")
        if val: keys["deepseek"] = val
    return keys

_LLM_KEYS = _load_llm_keys()

# ── Handlers de herramientas ──────────────────────────────────────────────────

def tool_poli_chat(args: dict) -> dict:
    """Procesa un mensaje conversacional hacia Poli.
    
    Interpreta el mensaje, elige la rutina Poli adecuada, ejecuta y
    devuelve una respuesta estructurada.
    """
    mensaje = args.get("mensaje", "").strip()
    if not mensaje:
        return {"ok": False, "error": "mensaje vacío"}
    
    mode = args.get("mode", "") or ""
    session_id = args.get("session", _STATE.default_session)
    
    # 1. Cambiar modo si se especifica
    if mode:
        r = _STATE.exec(
            f'D SWITCH^PERSONALITY("{session_id}","{mode}")',
            gas=30000,
        )
        if not r.get("ok"):
            return {"ok": False, "error": str(r.get("state",{}).get("error",{}).get("zerror",""))}
    
    # 2. Determinar acción según el mensaje
    msg_lower = mensaje.lower()
    
    if any(w in msg_lower for w in ["quién eres", "personalidad", "modo", "switch"]):
        # Consulta de personalidad
        parts = mensaje.split()
        target_mode = parts[-1] if len(parts) > 1 and not parts[-1].startswith(("cómo", "qué", "cuál")) else ""
        if target_mode and target_mode not in ("eres", "personalidad", "modo", "switch"):
            r = _STATE.exec(f'S ^R=$$ACTIVE^PERSONALITY("{session_id}")', gas=10000)
            active = None
            for g in (r.get("globals") or []):
                if g.get("ns") == "R":
                    active = g.get("value")
                    break
            return {
                "ok": r.get("ok"),
                "active_mode": active,
                "mensaje": f"Modo activo: {active}" if active else "No hay modo activo",
                "globals": _STATE._globals_dict(),
            }
        else:
            r = _STATE.exec(f'D LIST^PERSONALITY(.modes,"") S ^LC=modes', gas=50000)
            modes = []
            i = 1
            while True:
                val = None
                for g in (r.get("globals") or []):
                    if g.get("ns") == "LC":
                        val = g.get("value")
                    if g.get("ns") == "modes" and g.get("subs") == [i]:
                        modes.append(g.get("value"))
                if val is not None and i > val:
                    break
                i += 1
            return {
                "ok": r.get("ok"),
                "modes": modes,
                "count": val,
                "mensaje": f"Modos disponibles ({int(val) if val else 0}): {', '.join(str(m) for m in modes)}" if val else "No hay modos",
            }
    
    elif any(w in msg_lower for w in ["piensa", "thinking", "razona", "analiza"]):
        # Thinking / razonamiento
        params = {"type": "deductive", "agent": "hermes"}
        r = _STATE.exec(
            f'N m S m("type")="{params["type"]}",m("agent")="{params["agent"]}" '
            f'D THINKING^THINKING("{session_id}","general",.m)',
            gas=50000,
        )
        result_val = None
        for g in (r.get("globals") or []):
            if g.get("ns") == "THINKING" and len(g.get("subs") or []) >= 3:
                result_val = g.get("value")
                break
        return {
            "ok": r.get("ok"),
            "result": result_val,
            "execution": r.get("execution"),
            "error": r.get("state", {}).get("error"),
        }
    
    elif any(w in msg_lower for w in ["recuerda", "memory", "memoria", "guarda"]):
        # MEMORY: guardar o recuperar
        if any(w in msg_lower for w in ["guarda", "save", "guardar", "almacena"]):
            # Extraer clave/valor del mensaje
            content = mensaje
            key = f"chat_{abs(hash(content)) % 1000000}"
            r = _STATE.exec(
                f'D SAVE^MEMORY("{session_id}","{key}","{content}","")',
                gas=30000,
            )
            return {
                "ok": r.get("ok"),
                "action": "saved",
                "key": key,
                "error": r.get("state", {}).get("error"),
            }
        else:
            r = _STATE.exec(
                f"S i=0,key=\"\" F S key=$O(^MEMORY(\"{session_id}\",key)) Q:key=\"\"  S:key'=\"idx\" i=i+1,^TMP(i)=key,^TMP(i,\"v\")=$G(^MEMORY(\"{session_id}\",key)) S ^LC=i",
                gas=30000,
            )
            memories = []
            for g in (r.get("globals") or []):
                subs = g.get("subs") or []
                if g.get("ns") == "TMP" and len(subs) == 1 and subs[0] not in ("v",):
                    key = g.get("value")
                    if key:
                        memories.append({"key": str(key), "value": None})
                if g.get("ns") == "TMP" and len(subs) == 2 and subs[1] == "v":
                    if memories:
                        memories[-1]["value"] = g.get("value")
            return {
                "ok": r.get("ok"),
                "memories": memories[:10],
            }
    
    elif any(w in msg_lower for w in ["wiki", "documenta", "knowledge"]):
        # WIKI
        if any(w in msg_lower for w in ["busca", "search", "buscar"]):
            query = mensaje.split(" ", 1)[-1] if " " in mensaje else ""
            r = _STATE.exec(
                f'D BYTAG^WIKI("{query}") S ^RC=$G(^TMP("list"))',
                gas=30000,
            )
            results = []
            for g in (r.get("globals") or []):
                if g.get("ns") == "TMP" and g.get("subs") and "list" in str(g.get("subs")):
                    results.append(g.get("value"))
            return {
                "ok": r.get("ok"),
                "results": results[:10],
            }
        else:
            r = _STATE.exec(
                f'D RECENT^WIKI(5) S ^RC=$G(^TMP("list"))',
                gas=30000,
            )
            recent = None
            for g in (r.get("globals") or []):
                if g.get("ns") == "RC":
                    recent = g.get("value")
            return {
                "ok": r.get("ok"),
                "recent_count": recent,
            }
    
    elif any(w in msg_lower for w in ["decide", "decisión", "decision", "log"]):
        # DECISIONS
        esc_msj = mensaje.replace('"', '""')
        r = _STATE.exec(
            f'S ^DIDRESULT=$$LOG^DECISIONS("hermes","consulta","{esc_msj}","[]","","active")',
            gas=30000,
        )
        did = None
        for g in (r.get("globals") or []):
            if g.get("ns") == "DIDRESULT":
                did = g.get("value")
        return {
            "ok": r.get("ok"),
            "decision_id": did,
            "error": r.get("state", {}).get("error"),
        }
    
    elif any(w in msg_lower for w in ["status", "estado", "health"]):
        # Status general
        r = _STATE.exec(
            f'D LIST^PERSONALITY(.modes,"") S ^LC=modes '
            f'D RECENT^WIKI(5) S ^RC=$G(^TMP("list"))',
            gas=50000,
        )
        return {
            "ok": r.get("ok"),
            "globals": _STATE._globals_dict(),
            "execution": r.get("execution"),
        }
    
    else:
        # Fallback: responder con el modo activo
        r = _STATE.exec(
            f'S ^R=$$ACTIVE^PERSONALITY("{session_id}")',
            gas=10000,
        )
        active = None
        for g in (r.get("globals") or []):
            if g.get("ns") == "R":
                active = g.get("value")
                break
        return {
            "ok": r.get("ok"),
            "response": f"Modo activo: {active}. ¿En qué puedo ayudarte?",
            "active_mode": active,
        }

def tool_poli_exec(args: dict) -> dict:
    """Ejecuta código M arbitrario sobre el estado Poli actual."""
    source = args.get("source", "").strip()
    if not source:
        return {"ok": False, "error": "source vacío"}
    gas = args.get("gas_limit", 50000)
    r = _STATE.exec(source, gas=gas)
    result = {
        "ok": r.get("ok"),
        "execution": r.get("execution"),
        "globals": [],
    }
    for g in (r.get("globals") or []):
        ns = g.get("ns", "")
        subs = g.get("subs") or []
        result["globals"].append({
            "name": f"^{ns}" + (f"({','.join(str(s) for s in subs)})" if subs else ""),
            "value": g.get("value"),
        })
    err = r.get("state", {}).get("error")
    if err:
        result["error"] = str(err.get("zerror", ""))
    return result

def tool_poli_status(args: dict) -> dict:
    """Snapshot completo del estado actual de Poli."""
    r = _STATE.exec(
        f'D LIST^PERSONALITY(.modes,"") S ^LC=modes '
        f'S ^R=$$ACTIVE^PERSONALITY("{_STATE.default_session}")',
        gas=50000,
    )
    active = None
    mode_count = 0
    for g in (r.get("globals") or []):
        if g.get("ns") == "R":
            active = g.get("value")
        if g.get("ns") == "LC":
            mode_count = g.get("value") or 0
    return {
        "ok": r.get("ok"),
        "active_mode": active,
        "mode_count": int(mode_count) if mode_count else 0,
        "routines_loaded": list(_ROUTINES.keys()),
        "globals": _STATE._globals_dict(),
        "execution": r.get("execution"),
    }

def tool_poli_seed(args: dict) -> dict:
    """Sembrar modos de personalidad por defecto (oracle, mentor, critic, creative)."""
    r = _STATE.seed()
    return {
        "ok": r.get("ok"),
        "error": r.get("error"),
        "mensaje": "Modos sembrados correctamente" if r.get("ok") else "Error al sembrar modos",
    }

def tool_poli_llm(args: dict) -> dict:
    """LLM call nativa desde el MVM. Usa $LLM (fork+await automático).
    Respeta la personalidad activa: lee provider/model de ^PERSONALITY.
    """
    prompt = args.get("prompt", "").strip()
    if not prompt:
        return {"ok": False, "error": "prompt vacío"}
    system = args.get("system", "")
    session_id = args.get("session", _STATE.default_session)
    
    # 1. Leer personalidad activa y su configuración de modelo
    r = _STATE.exec(
        f'S ^MODE=$$ACTIVE^PERSONALITY("{session_id}") '
        f'S ^PROV=$G(^PERSONALITY($G(^MODE),"provider")) '
        f'S ^MOD=$G(^PERSONALITY($G(^MODE),"model"))',
        gas=30000,
    )
    active_mode = None
    provider = None
    model = None
    for g in (r.get("globals") or []):
        ns = g.get("ns")
        if ns == "MODE":
            active_mode = g.get("value")
        elif ns == "PROV":
            provider = str(g.get("value", ""))
        elif ns == "MOD":
            model = str(g.get("value", ""))
    
    # 2. Fallback a args o defaults
    if not provider or provider in ("", "None", "0"):
        provider = args.get("provider", "deepseek")
    if not model or model in ("", "None", "0"):
        model = args.get("model", "deepseek-v4-flash")
    
    # 3. Modo simbólico = sin LLM
    if provider == "symbolic":
        return {
            "ok": True,
            "response": "[Modo simbólico — sin LLM]",
            "mode": "symbolic",
            "personality": active_mode,
        }
    
    gas = args.get("gas_limit", 500000)
    esc_prompt = prompt.replace('"', '""')
    esc_system = system.replace('"', '""')
    source = f'S ^R=$DEVICE("llm:call","{esc_prompt}","{esc_system}","{provider}","{model}")'
    
    import time as _time
    start = _time.time()
    r = _STATE.exec(source, gas=gas)
    elapsed = _time.time() - start
    
    result = None
    for g in (r.get("globals") or []):
        if g.get("ns") == "R":
            result = g.get("value")
            break
    
    return {
        "ok": r.get("ok"),
        "response": result,
        "elapsed": f"{elapsed:.1f}s",
        "execution": r.get("execution"),
        "personality": active_mode,
        "mode": f"{provider}/{model}",
        "error": r.get("state", {}).get("error"),
    }


def tool_poli_fiber(args: dict) -> dict:
    """Gestiona fibers: lanza M code en background thread o espera resultado.
    
    action='spawn': lanza source en thread separado, devuelve fiber_id
    action='join': espera que un bg fiber termine, devuelve su resultado
    """
    action = args.get("action", "spawn")
    if action == "spawn":
        source = args.get("source", "").strip()
        if not source:
            return {"ok": False, "error": "source vacío"}
        esc = source.replace('"', '""')
        r = _STATE.exec(f'S ^FIBER=$FIBER("bg","{esc}")', gas=20000)
        fid = None
        for g in (r.get("globals") or []):
            if g.get("ns") == "FIBER":
                fid = g.get("value")
                break
        return {
            "ok": r.get("ok"),
            "action": "spawned",
            "fiber_id": fid,
            "execution": r.get("execution"),
            "error": r.get("state", {}).get("error"),
        }
    elif action == "join":
        fid = args.get("fiber_id", 0)
        r = _STATE.exec(f'S ^RESULT=$FIBER("join",{fid}) S ^DONE=1', gas=500000)
        result = None
        for g in (r.get("globals") or []):
            if g.get("ns") == "RESULT":
                result = g.get("value")
                break
        done = any(g.get("ns") == "DONE" for g in (r.get("globals") or []))
        return {
            "ok": r.get("ok"),
            "action": "joined",
            "fiber_id": fid,
            "result": result,
            "done": done,
            "execution": r.get("execution"),
            "error": r.get("state", {}).get("error"),
        }
    return {"ok": False, "error": f"unknown action: {action}"}


def tool_poli_http(args: dict) -> dict:
    """HTTP calls via $DEVICE nativo."""
    method = args.get("method", "get").lower()
    url = args.get("url", "").strip()
    if not url:
        return {"ok": False, "error": "url vacía"}
    body = args.get("body", "")
    if method == "get":
        src = f'S ^R=$DEVICE("http:get","{url}")'
    elif method == "post":
        esc_body = body.replace('"', '""')
        src = f'S ^R=$DEVICE("http:post","{url}","{esc_body}")'
    else:
        return {"ok": False, "error": f"unsupported method: {method}"}
    import time as _time
    start = _time.time()
    r = _STATE.exec(src, gas=20000)
    elapsed = _time.time() - start
    result = None
    for g in (r.get("globals") or []):
        if g.get("ns") == "R":
            result = g.get("value")
            break
    return {
        "ok": r.get("ok"),
        "method": method.upper(),
        "url": url,
        "response": result[:2000] if result else None,
        "elapsed": f"{elapsed:.1f}s",
        "error": r.get("state", {}).get("error"),
    }

# ── Definición de herramientas ────────────────────────────────────────────────
TOOLS = [
    {
        "name": "poli_chat",
        "description": "Mensaje conversacional a Poli. Interpreta el mensaje y elige la rutina adecuada (personalidad, thinking, wiki, memory, decisiones).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mensaje": {"type": "string", "description": "Mensaje o consulta para Poli"},
                "mode": {"type": "string", "description": "Cambiar a este modo de personalidad (opcional)", "default": ""},
                "session": {"type": "string", "description": "ID de sesión", "default": "hermes"},
            },
            "required": ["mensaje"],
        },
    },
    {
        "name": "poli_exec",
        "description": "Ejecutar código M arbitrario sobre el estado actual de Poli (con rutinas y globales cargados).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Código M a ejecutar"},
                "gas_limit": {"type": "integer", "description": "Límite de gas", "default": 50000},
            },
            "required": ["source"],
        },
    },
    {
        "name": "poli_status",
        "description": "Estado completo de Poli: modo activo, modos disponibles, rutinas cargadas, globales.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "poli_seed",
        "description": "Sembrar modos de personalidad por defecto (oracle, mentor, critic, creative).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "poli_llm",
        "description": "LLM call nativa desde el MVM Rust (sin Python HTTP). Usa $DEVICE('llm:call') fork+await con yield automático.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Prompt para el LLM"},
                "system": {"type": "string", "description": "System prompt", "default": ""},
                "provider": {"type": "string", "description": "deepseek (default) u openrouter", "default": "deepseek"},
                "model": {"type": "string", "description": "deepseek-v4-flash (default) o deepseek-v4-pro", "default": "deepseek-v4-flash"},
                "mode": {"type": "string", "description": "symbolic = sin LLM", "default": ""},
                "gas_limit": {"type": "integer", "description": "Gas para el MVM", "default": 500000},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "poli_fiber",
        "description": "Gestiona fibers: spawn lanza M code en background thread, join espera resultado.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["spawn", "join"], "description": "spawn=lanza thread, join=espera resultado"},
                "source": {"type": "string", "description": "Código M a ejecutar en background (para action=spawn)"},
                "fiber_id": {"type": "integer", "description": "ID del fiber a esperar (para action=join)"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "poli_http",
        "description": "HTTP calls via $DEVICE nativo en Rust. GET o POST.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": ["get", "post"], "description": "Método HTTP", "default": "get"},
                "url": {"type": "string", "description": "URL a consultar"},
                "body": {"type": "string", "description": "Body para POST (JSON string)", "default": ""},
            },
            "required": ["url"],
        },
    },
]

HANDLERS = {
    "poli_chat": tool_poli_chat,
    "poli_exec": tool_poli_exec,
    "poli_status": tool_poli_status,
    "poli_seed": tool_poli_seed,
    "poli_llm": tool_poli_llm,
    "poli_fiber": tool_poli_fiber,
    "poli_http": tool_poli_http,
}

# ── Seed automático al arranque ──────────────────────────────────────────────
# Intentar sembrar modos al iniciar (silenciosamente)
try:
    _STATE.seed()
except Exception:
    pass

# ── Protocolo MCP stdio ─────────────────────────────────────────────────────
def send(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def handle(msg):
    mid = msg.get("id")
    method = msg.get("method", "")
    if method == "initialize":
        send({
            "jsonrpc": "2.0", "id": mid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False, "toolCount": 7},
                },
                "serverInfo": {"name": "poli-server", "version": "0.1.0"},
            },
        })
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name", "")
        args = params.get("arguments", {})
        handler = HANDLERS.get(name)
        if handler:
            try:
                result = handler(args)
                send({
                    "jsonrpc": "2.0", "id": mid,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                    },
                })
            except Exception as e:
                logger.exception("Handler error")
                send({
                    "jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32603, "message": str(e)},
                })
        else:
            send({
                "jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"Unknown tool: {name}"},
            })
    elif method == "notifications/initialized":
        pass
    else:
        send({
            "jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        })

if __name__ == "__main__":
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            handle(msg)
        except json.JSONDecodeError:
            send({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}})
