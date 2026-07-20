"""Gateway de LLMs para Poli — rutea a DeepSeek, OpenRouter o ningún LLM según modo.

Modos:
  - symbolic (default): sin LLM, razonamiento MVM puro
  - deep: DeepSeek V4 Flash vía OpenRouter
  - fast: modelo rápido/barato vía OpenRouter (Llama 3-8B, Haiku, etc.)
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# ── Modelos por modo ─────────────────────────────────────────────────────────
MODELS = {
    "deep": {
        "model": "deepseek/deepseek-chat",  # DeepSeek V4 Flash
        "provider": "openrouter",
        "description": "Razonamiento profundo (DeepSeek V4 Flash)",
    },
    "fast": {
        "model": "meta-llama/llama-3.1-8b-instruct",  # Rápido y barato
        "provider": "openrouter",
        "description": "Razonamiento rápido (Llama 3.1-8B)",
    },
    "symbolic": {
        "model": None,
        "provider": None,
        "description": "Razonamiento simbólico MVM puro",
    },
}

# ── Endpoints ────────────────────────────────────────────────────────────────
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

_OPENROUTER_KEY = None
_DEEPSEEK_KEY = None


def _load_keys():
    global _OPENROUTER_KEY, _DEEPSEEK_KEY
    if _OPENROUTER_KEY is not None:
        return
    try:
        env_path = os.path.expanduser("~/AppData/Local/hermes/.env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("OPENROUTER_API_KEY=") and not line.startswith("#"):
                        _OPENROUTER_KEY = line.split("=", 1)[1].strip().strip("'\"")
                    elif line.startswith("DEEPSEEK_API_KEY=") and not line.startswith("#"):
                        _DEEPSEEK_KEY = line.split("=", 1)[1].strip().strip("'\"")
    except Exception as e:
        logger.warning("Error loading API keys: %s", e)
    
    # Fallback a env vars
    if not _OPENROUTER_KEY:
        _OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
    if not _DEEPSEEK_KEY:
        _DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")


def _call_openrouter(prompt: str, model: str, system_prompt: str = "") -> dict:
    """Llama a OpenRouter con un modelo específico."""
    _load_keys()
    if not _OPENROUTER_KEY:
        return {"ok": False, "error": "OPENROUTER_API_KEY no configurada"}
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": 4096,
        "temperature": 0.7,
    }).encode("utf-8")
    
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_OPENROUTER_KEY}",
            "HTTP-Referer": "https://github.com/GonzaloMonzonC/poli",
        },
        method="POST",
    )
    
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {
                "ok": True,
                "response": content,
                "model": result.get("model", model),
                "usage": result.get("usage", {}),
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def llm_call(prompt: str, mode: str = "symbolic", system_prompt: str = "", session_state: dict = None) -> dict:
    """Punto de entrada unificado — llama al LLM según el modo.
    
    Args:
        prompt: Texto de entrada.
        mode: "deep" | "fast" | "symbolic"
        system_prompt: Contexto de sistema (personalidad, etc.)
        session_state: Estado opcional de sesión Poli para contexto.
    
    Returns:
        dict con ok, response/error, mode, model usado.
    """
    mode = mode.lower().strip()
    if mode not in MODELS:
        mode = "symbolic"
    
    cfg = MODELS[mode]
    
    if mode == "symbolic":
        return {
            "ok": True,
            "response": None,
            "mode": "symbolic",
            "model": None,
            "note": "Modo simbólico — sin LLM",
        }
    
    if cfg["provider"] == "openrouter":
        result = _call_openrouter(prompt, cfg["model"], system_prompt)
        result["mode"] = mode
        result["model_config"] = cfg["model"]
        return result
    
    return {"ok": False, "error": f"Provider no soportado: {cfg.get('provider')}"}
