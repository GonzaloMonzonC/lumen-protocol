#!/usr/bin/env python3
"""MCP server for Poli — el agente MVM polimórfico.

Expone las rutinas Poli (PERSONALITY, THINKING, WIKI, DECISIONS, MEMORY, UTILS)
como herramientas MCP para que Hermes las invoque conversacionalmente. Mantiene
estado de sesión persistente entre invocaciones.
"""
from __future__ import annotations
import hashlib
import hmac
import json, logging, os, sys
import time as _time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pdb"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lumen_mlight import execute as ml_execute
from poli_gateway import llm_call, MODELS

# ── PDB SQLite path (persistencia real) ──────────────────────────────────────
PDB_SQLITE = str(Path.home() / "pdb-data" / "lumen-pdb.db")

# ── Config segura (fuera del repo) ───────────────────────────────────────────
_CONFIG_FILE = Path.home() / "AppData/Local/hermes/poli_config.json"
_CONFIG_CACHE = None  # cargado lazy en init

def _load_config() -> dict[str, str]:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    if _CONFIG_FILE.exists():
        try:
            _CONFIG_CACHE = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            _CONFIG_CACHE = {}
    else:
        _CONFIG_CACHE = {}
    return _CONFIG_CACHE

def _hmac_sign(body: str, secret: str) -> tuple[str, str]:
    """Calcula X-DDP-HMAC + X-DDP-Timestamp para requests a CF Workers.
    Formato: HMAC-SHA256(timestamp + body + secret) en hex."""
    ts = str(int(_time.time()))
    sig = hmac.new(secret.encode("utf-8"),
                   (ts + body + secret).encode("utf-8"),
                   hashlib.sha256).hexdigest()
    return sig, ts

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

def _sanitize_globals(globals_list: list) -> list:
    """Convierte cualquier valor bytes a string en una lista de globals."""
    clean = []
    for g in globals_list:
        entry = {}
        for k, v in g.items():
            if isinstance(v, bytes):
                entry[k] = v.decode("utf-8", errors="replace")
            elif isinstance(v, list):
                entry[k] = [s.decode("utf-8", errors="replace") if isinstance(s, bytes) else s for s in v]
            else:
                entry[k] = v
        clean.append(entry)
    return clean

def _decode_subkey(data: bytes) -> list:
    """Decodifica subkey MUMPS → lista de subscripts.
    Formato: \\x02<str>\\xff\\x02<str>\\xff...
    """
    subs = []
    remaining = data
    while remaining:
        if remaining[0:1] != b'\x02':
            break
        remaining = remaining[1:]
        idx = remaining.find(b'\xff')
        if idx < 0:
            break
        subs.append(remaining[:idx].decode("utf-8", errors="replace"))
        remaining = remaining[idx+1:]
    return subs

def _extract_routines_from_globals(globals_list: list) -> dict[str, str]:
    """Extrae rutinas de ^ROUTINE global en la PDB.
    
    ^ROUTINE(NOMBRE, linea) = "codigo M"
    Concatena líneas en orden numérico para formar la rutina.
    """
    routines = {}
    # Indexar por nombre de rutina
    named: dict[str, dict[int, str]] = {}
    for g in globals_list:
        ns = g.get("ns", "")
        value = g.get("value", "")
        # ^ROUTINE(NOMBRE, N) → ns = "ROUTINE", subs = [NOMBRE, N]
        if ns == "ROUTINE":
            subs = g.get("subs", [])
            if len(subs) >= 2:
                routine_name = str(subs[0]).upper()
                if isinstance(subs[1], (int, float)):
                    line_no = int(subs[1])
                    if routine_name not in named:
                        named[routine_name] = {}
                    named[routine_name][line_no] = str(value)
    for rname, lines in named.items():
        code = "\n".join(lines[k] for k in sorted(lines.keys()))
        routines[rname] = code
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
        # Cargar config segura en ^CONFIG
        cfg = _load_config()
        if cfg:
            exec_parts = []
            for k, v in cfg.items():
                ev = v.replace('"', '""')
                exec_parts.append(f'S ^CONFIG("{k}")="{ev}"')
            if exec_parts:
                r = ml_execute(" ".join(exec_parts), routines=_ROUTINES, globals_=self.globals, gas_limit=10000, sqlite_path=PDB_SQLITE)
                if r.get("ok"):
                    self.globals = r.get("globals") or self.globals
                    self.globals = _sanitize_globals(self.globals)
        # Cargar rutinas desde ^ROUTINE en PDB
        pdb_routines = _extract_routines_from_globals(self.globals)
        if pdb_routines:
            _ROUTINES.update(pdb_routines)
    
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
        luego carga Synapse Studio skills desde .mac files.
        """
        # Seed básico
        r = ml_execute(
            source='D SEED^PERSONALITY S ^PERSONALITY("critic","provider")="deepseek" S ^PERSONALITY("critic","model")="deepseek-v4-flash"',
            routines=_ROUTINES,
            globals_=self.globals,
            gas_limit=60000,
            sqlite_path=PDB_SQLITE,
        )
        if r.get("ok"):
            self.globals = r.get("globals") or self.globals
            self.globals = _sanitize_globals(self.globals)
        
        # Cargar todos los datos de SQLite a self.globals para que exec() los vea
        try:
            import sqlite3
            db = sqlite3.connect(PDB_SQLITE)
            rows = db.execute("SELECT ns, subkey, value FROM _globals").fetchall()
            db.close()
            for ns, subkey_b, value in rows:
                # Decodificar subkey MUMPS → lista de subscripts
                subs = _decode_subkey(subkey_b) if isinstance(subkey_b, bytes) else []
                self.globals.append({"ns": ns, "subs": subs, "value": value})
        except Exception:
            pass
        # Sanitizar después de cargar de SQLite
        self.globals = _sanitize_globals(self.globals)
        
        # Cargar Synapse Studio skills desde archivos .mac
        skills_dir = Path(__file__).resolve().parent / "synapse" / "skills"
        if skills_dir.exists():
            mac_files = sorted(skills_dir.glob("*.mac"))
            for mf in mac_files:
                try:
                    code = mf.read_text(encoding="utf-8")
                    # Quitar líneas de comentario y Q
                    clean = []
                    for l in code.split("\n"):
                        s = l.strip()
                        if s.startswith(";") or s == " ;" or s == "Q":
                            continue
                        clean.append(l)
                    if clean:
                        r2 = ml_execute(
                            "\n".join(clean),
                            routines=_ROUTINES,
                            globals_=self.globals,
                            gas_limit=200000,
                            sqlite_path=PDB_SQLITE,
                        )
                        if r2.get("ok"):
                            self.globals = r2.get("globals") or []
                            self.globals = _sanitize_globals(self.globals)
                except Exception:
                    pass
        
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
            self.globals = r.get("globals") or self.globals
            # Sanitizar: convertir cualquier bytes a string
            self.globals = _sanitize_globals(self.globals)
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
    
    # Activar Smith si el mensaje contiene [Smith]
    if "[smith]" in mensaje.lower() or "[sm]" in mensaje.lower():
        # Stripear el tag y pasar el mensaje limpio
        clean = mensaje.replace("[Smith]", "").replace("[smith]", "").replace("[SM]", "").replace("[sm]", "").strip()
        return tool_poli_smith({"mensaje": clean or mensaje, "session": session_id})
    
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
        # Fallback: responder con LLM usando la personalidad activa
        r = _STATE.exec(
            f'S ^M=$$ACTIVE^PERSONALITY("{session_id}") '
            f'S ^I=$G(^PERSONALITY($G(^M),"identity")) '
            f'S ^P=$G(^PERSONALITY($G(^M),"provider")) '
            f'S ^D=$G(^PERSONALITY($G(^M),"model"))',
            gas=30000,
        )
        active = None
        identity = ""
        provider = ""
        model = ""
        for g in (r.get("globals") or []):
            ns = g.get("ns")
            if ns == "M": active = g.get("value")
            elif ns == "I": identity = str(g.get("value", ""))
            elif ns == "P": provider = str(g.get("value", ""))
            elif ns == "D": model = str(g.get("value", ""))

        if provider and provider not in ("symbolic", "", "None", "0"):
            esc_msg = mensaje.replace('"', '""')
            esc_sys = identity.replace('"', '""')
            if not model or model in ("", "None", "0"):
                model = "deepseek-v4-flash"
            src = f'S ^R=$DEVICE("llm:call","{esc_msg}","{esc_sys}","{provider}","{model}")'
            r2 = _STATE.exec(src, gas=200000)
            result = None
            for g in (r2.get("globals") or []):
                if g.get("ns") == "R":
                    result = g.get("value")
                    break
            return {
                "ok": r2.get("ok"),
                "response": result,
                "active_mode": active,
                "personality_used": active,
            }
        else:
            return {
                "ok": r.get("ok"),
                "response": f"Modo activo: {active}. En qu puedo ayudarte?",
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
    """HTTP calls con HMAC signing para CF Workers.
    Lee DDP_HMAC_KEY de ^CONFIG para firmar requests a workers.dev.
    Fallback a $DEVICE nativo si no es worker CF o no hay key.
    """
    method = args.get("method", "get").lower()
    url = args.get("url", "").strip()
    if not url:
        return {"ok": False, "error": "url vacía"}
    body = args.get("body", "")
    
    # Intentar HMAC signing si es workers.dev
    hmac_key = None
    r = _STATE.exec('S ^K=$G(^CONFIG("ddp_hmac_key"))', gas=5000)
    for g in (r.get("globals") or []):
        if g.get("ns") == "K" and g.get("value"):
            hmac_key = str(g.get("value"))
    
    if hmac_key and ".workers.dev" in url:
        # HMAC path: usar Python nativo, no $DEVICE
        try:
            start = _time.time()
            data = body.encode() if body else b""
            req = Request(url, data=data, method=method.upper())
            sig, ts = _hmac_sign(body or "", hmac_key)
            req.add_header("X-DDP-HMAC", sig)
            req.add_header("X-DDP-Timestamp", ts)
            req.add_header("User-Agent", "Hermes-MCP-Bridge/2.0")
            if body:
                req.add_header("Content-Type", "application/json")
            
            with urlopen(req, timeout=15) as resp:
                result = resp.read().decode()
            elapsed = _time.time() - start
            return {
                "ok": True,
                "method": method.upper(),
                "url": url,
                "response": result[:2000] if result else None,
                "elapsed": f"{elapsed:.1f}s",
                "hmac": True,
            }
        except Exception as e:
            elapsed = _time.time() - start
            return {
                "ok": False,
                "method": method.upper(),
                "url": url,
                "error": str(e),
                "elapsed": f"{elapsed:.1f}s",
                "hmac": True,
            }
    
    # Fallback: $DEVICE nativo (sin HMAC)
    if method == "get":
        src = f'S ^R=$DEVICE("http:get","{url}")'
    elif method == "post":
        esc_body = body.replace('"', '""')
        src = f'S ^R=$DEVICE("http:post","{url}","{esc_body}")'
    else:
        return {"ok": False, "error": f"unsupported method: {method}"}
    
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
        "hmac": False,
        "error": r.get("state", {}).get("error"),
    }

def tool_poli_smith(args: dict) -> dict:
    """SMITH MODE: orquestación multi-personalidad.
    Analiza la consulta, detecta dominios, activa perfiles expertos en paralelo
    y sintetiza respuesta unificada.
    """
    mensaje = args.get("mensaje", "").strip()
    if not mensaje:
        return {"ok": False, "error": "mensaje vacío"}
    session_id = args.get("session", "hermes")
    
    # 1. Detectar dominios en Python
    # Normalizar: quitar tildes y convertir a minúsculas
    import unicodedata
    q = unicodedata.normalize("NFKD", mensaje.lower()).encode("ascii", "ignore").decode("ascii")
    domains_found = []
    
    # Palabras clave por dominio → personalidad (todo en minúsculas, sin tildes)
    domain_keywords = {
        "medico-general": ["salud", "medico", "medica", "enfermedad", "sintoma", "hospital", "clinico", "dolor", "paciente", "diagnostico", "tratamiento"],
        "nutricionista-clinico": ["nutricion", "dieta", "alimento", "vitamina", "sobrepeso", "obesidad", "comida", "dietetico"],
        "abogado-corporativo": ["legal", "abogado", "ley", "contrato", "demanda", "tribunal", "litigio", "abogacia", "permiso", "licencia", "normativa", "regulacion", "juridico"],
        "finance-asesor-de-inversiones": ["finanza", "financiero", "inversion", "ahorro", "presupuesto", "contable", "impuesto", "rentabilidad", "capital", "credito", "prestamo"],
        "education-pedagogo-innovador": ["educacion", "educativo", "aprender", "ensenar", "curso", "formacion", "estudiante", "pedagogia", "escuela", "colegio", "aula", "docente"],
        "engineering-senior-developer": ["programacion", "software", "codigo", "programa", "desarroll", "app", "algoritmo", "sistema", "tecnologia", "informatico"],
        "marketing-growth-hacker": ["negocio", "empresa", "startup", "emprend", "mercad", "venta", "crecimiento", "cliente", "comercial", "marketing"],
        "agriculture-director-de-sostenibilidad": ["ambiente", "ambiental", "sostenible", "sostenibilidad", "ecologia", "reciclaje", "energia", "carbono", "verde", "renovable", "ecologico", "naturaleza"],
        "sales-account-strategist": ["venta", "cliente", "comercial", "negociacion", "cuenta", "lead", "prospecto"],
    }
    
    for personality, keywords in domain_keywords.items():
        for kw in keywords:
            if kw in q:
                domains_found.append(personality)
                break
    
    # Si no se detectó nada, usar creative
    if not domains_found:
        domains_found.append("creative")
    
    domains_found = list(dict.fromkeys(domains_found))  # dedup
    domains_count = len(domains_found)
    
    # 4. Ejecutar personalidades (secuencial, 2 max - cabe en Cloudflare 30s)
    # 4. Ejecutar personalidades secuencial (hasta implementar $SMITH() en Rust)
    partials = {}
    for mode in domains_found[:2]:
        r4 = _STATE.exec(
            f'S ^ID=$G(^PERSONALITY("{mode}","identity")) '
            f'S ^P=$G(^PERSONALITY("{mode}","provider")) '
            f'S ^M=$G(^PERSONALITY("{mode}","model"))',
            gas=10000,
        )
        identity = ""
        provider = ""
        model = ""
        for g in (r4.get("globals") or []):
            ns = g.get("ns")
            if ns == "ID": identity = str(g.get("value", ""))
            elif ns == "P": provider = str(g.get("value", ""))
            elif ns == "M": model = str(g.get("value", ""))
        
        if not provider or provider in ("symbolic", "", "None", "0"):
            provider = "deepseek"
            model = "deepseek-v4-flash"
            if not identity:
                identity = f"Eres un asesor experto en {mode}. Responde con claridad."
        if not model or model in ("", "None", "0"):
            model = "deepseek-v4-flash"
        esc_msg = mensaje.replace('"', '""')
        esc_sys = identity.replace('"', '""')
        src = f'S ^R=$DEVICE("llm:call","{esc_msg}","{esc_sys}","{provider}","{model}")'
        r5 = _STATE.exec(src, gas=500000)
        result = None
        for g in (r5.get("globals") or []):
            if g.get("ns") == "R":
                result = g.get("value")
                break
        partials[mode] = result
    
    # 5. Sintetizar
    if len(partials) <= 1:
        response = next(iter(partials.values())) if partials else "No se pudieron generar respuestas"
    else:
        # Síntesis: unificar respuestas
        synthesis_input = "\n\n".join(
            f"[{mode}]: {resp}" for mode, resp in partials.items() if resp
        )
        esc_synth = synthesis_input.replace('"', '""')
        esc_q = mensaje.replace('"', '""')
        synthesis_sys = "Eres un sintetizador de perspectivas múltiples. Tu tarea es unificar las siguientes opiniones de expertos en una respuesta coherente, detectando puntos en común y tensiones creativas. Genera una síntesis que integre todas las perspectivas."
        esc_sys = synthesis_sys.replace('"', '""')
        src = f'S ^R=$DEVICE("llm:call","Sintetiza estas perspectivas para: {esc_q}\\n\\n{esc_synth}","{esc_sys}","deepseek","deepseek-v4-flash")'
        r6 = _STATE.exec(src, gas=200000)
        response = None
        for g in (r6.get("globals") or []):
            if g.get("ns") == "R":
                response = g.get("value")
                break
    
    return {
        "ok": True,
        "mode": "smith",
        "domains_detected": domains_count,
        "modes_activated": domains_found[:5],
        "modes_count": len(domains_found),
        "response": response,
        "partials": partials,
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
    {
        "name": "poli_smith",
        "description": "SMITH MODE: orquestación multi-personalidad. Analiza la consulta, detecta dominios, activa perfiles expertos en paralelo y sintetiza respuesta unificada.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mensaje": {"type": "string", "description": "Consulta o problema a analizar"},
                "session": {"type": "string", "description": "ID de sesión", "default": "hermes"},
            },
            "required": ["mensaje"],
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
    "poli_smith": tool_poli_smith,
}

# ── Seed automático al arranque ──────────────────────────────────────────────
# Intentar sembrar modos al iniciar (silenciosamente)
try:
    _STATE.seed()
    # Recargar active_mode después del seed
    session_id = _STATE.default_session
    r = _STATE.exec(
        f'S ^MODE=$$ACTIVE^PERSONALITY("{session_id}") '
        f'S ^PROV=$G(^PERSONALITY($G(^MODE),"provider")) '
        f'S ^MOD=$G(^PERSONALITY($G(^MODE),"model"))',
        gas=30000,
    )
    for g in (r.get("globals") or []):
        ns = g.get("ns")
        if ns == "MODE":
            _STATE.active_mode = g.get("value")
        elif ns == "PROV":
            _STATE.provider = str(g.get("value", ""))
        elif ns == "MOD":
            _STATE.model = str(g.get("value", ""))
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
                    "tools": {"listChanged": False, "toolCount": 8},
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
    # ── HTTP server (poli-api.cadences.app) ─────────────────────────────────
    import http.server, threading, urllib.parse
    POLI_HTTP_PORT = int(os.environ.get("POLI_HTTP_PORT", "8082"))
    
    class PoliHTTPHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _json(self, code, obj):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(obj, ensure_ascii=False).encode())
        def do_GET(self):
            if self.path == "/health":
                return self._json(200, {"ok": True, "name": "poli", "status": "healthy"})
            self._json(404, {"error": "not found"})
        def do_POST(self):
            if self.path == "/v1/chat":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length)) if length else {}
                    msg = body.get("mensaje") or body.get("message") or ""
                    if not msg:
                        return self._json(400, {"ok": False, "error": "mensaje required"})
                    sid = body.get("session_id", "http_" + str(_time.time()).replace(".",""))
                    
                    # Detectar [Smith] en el mensaje
                    if "[smith]" in msg.lower() or "[sm]" in msg.lower():
                        clean = msg.replace("[Smith]","").replace("[smith]","").replace("[SM]","").replace("[sm]","").strip()
                        r = tool_poli_smith({"mensaje": clean or msg, "session": sid})
                        if r.get("mode") == "smith":
                            return self._json(200, {"ok": True, "mode": "smith", **r, "session_id": sid})
                        # Si Smith delegó a Creative, seguir flujo normal
                    
                    msg_esc = msg.replace('"', '""')
                    r = _STATE.exec(f'D CHAT^PERSONALITY("{msg_esc}")', gas=200000)
                    response = (r.get("state") or {}).get("output", "").strip() or "Poli no respondio"
                    return self._json(200, {"ok": True, "response": response, "session_id": sid})
                except Exception as e:
                    return self._json(500, {"ok": False, "error": str(e)})
            if self.path == "/v1/exec":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length)) if length else {}
                    code = body.get("code") or body.get("source") or ""
                    if not code:
                        return self._json(400, {"ok": False, "error": "code required"})
                    gas = body.get("gas_limit", 200000)
                    if not isinstance(gas, int) or gas < 1000:
                        gas = 200000
                    r = _STATE.exec(code, gas=gas)
                    state = r.get("state", {})
                    output = state.get("output", "")
                    error = state.get("error", {})
                    return self._json(200, {
                        "ok": r.get("ok", False),
                        "execution": r.get("execution", "error"),
                        "output": output,
                        "error": str(error.get("zerror", "")) if error else "",
                        "globals": [g for g in (r.get("globals") or []) if g.get("name","").startswith("^")],
                    })
                except Exception as e:
                    return self._json(500, {"ok": False, "error": str(e)})
            if self.path == "/v1/smith":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length)) if length else {}
                    msg = body.get("mensaje") or body.get("message") or ""
                    if not msg:
                        return self._json(400, {"ok": False, "error": "mensaje required"})
                    sid = body.get("session_id", "http_smith")
                    r = tool_poli_smith({"mensaje": msg, "session": sid})
                    if r.get("mode") == "creative":
                        # Delegado a creative - ejecutar LLM
                        esc_msg = msg.replace('"', '""')
                        ident = f'^I=$G(^PERSONALITY("creative","identity"))'
                        r2 = _STATE.exec(
                            f'S ^M=$$ACTIVE^PERSONALITY("{sid}") {ident} '
                            f'S ^P=$G(^PERSONALITY($G(^M),"provider")) '
                            f'S ^D=$G(^PERSONALITY($G(^M),"model"))',
                            gas=10000,
                        )
                        provider = None
                        identity = None
                        model = None
                        for g in (r2.get("globals") or []):
                            ns = g.get("ns")
                            if ns == "M": pass
                            elif ns == "I": identity = str(g.get("value", ""))
                            elif ns == "P": provider = str(g.get("value", ""))
                            elif ns == "D": model = str(g.get("value", ""))
                        if provider and provider not in ("symbolic", "", "None", "0"):
                            if not model or model in ("", "None", "0"):
                                model = "deepseek-v4-flash"
                            esc_sys = (identity or "").replace('"', '""')
                            src = f'S ^R=$DEVICE("llm:call","{esc_msg}","{esc_sys}","{provider}","{model}")'
                            r3 = _STATE.exec(src, gas=200000)
                            response = None
                            for g in (r3.get("globals") or []):
                                if g.get("ns") == "R":
                                    response = g.get("value")
                                    break
                            return self._json(200, {"ok": True, "mode": "creative", "response": response, "session_id": sid})
                    return self._json(200, {**r, "session_id": sid})
                except Exception as e:
                    return self._json(500, {"ok": False, "error": str(e)})
            self._json(404, {"error": "not found"})
    
    try:
        httpd = http.server.HTTPServer(("127.0.0.1", POLI_HTTP_PORT), PoliHTTPHandler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
    except OSError:
        pass
    
    # Si hay argumento --http-only, no entrar en MCP loop (standalone HTTP server)
    if len(sys.argv) > 1 and sys.argv[1] == "--http-only":
        import time
        while True:
            time.sleep(1)
        sys.exit(0)
    
    # ── MCP stdio loop
    # ────────────────────────────────────────────────────────────────────────────
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            handle(msg)
        except json.JSONDecodeError:
            send({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}})
