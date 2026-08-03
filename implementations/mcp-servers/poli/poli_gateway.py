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
# deep  → GLM 5.2 (Z.AI) con FALLBACK a DeepSeek (rate-limits de Z.AI por horas)
# fast  → DeepSeek V4 Flash directo (sin OpenRouter)
# symbolic → razonamiento simbólico MVM puro
MODELS = {
    "deep": {
        "model": "glm-5.2",                 # GLM 5.2 — thinking profundo (Z.AI)
        "provider": "zai",
        "fallback_model": "deepseek-chat",  # fallback: DeepSeek V4 Flash
        "fallback_provider": "deepseek",
        "description": "Razonamiento profundo (GLM 5.2 / Z.AI, fallback DeepSeek)",
    },
    "fast": {
        "model": "deepseek-chat",           # DeepSeek V4 Flash — trabajo ligero
        "provider": "deepseek",
        "description": "Razonamiento rápido (DeepSeek V4 Flash)",
    },
    "symbolic": {
        "model": None,
        "provider": None,
        "description": "Razonamiento simbólico MVM puro",
    },
}

# ── Endpoints ────────────────────────────────────────────────────────────────
ZAI_URL = "https://api.z.ai/api/paas/v4/chat/completions"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

_OPENROUTER_KEY = None  # legacy: ya NO se usa (OpenRouter retirado del gateway)
_ZAI_KEY = None
_DEEPSEEK_KEY = None


def _load_keys():
    global _ZAI_KEY, _DEEPSEEK_KEY, _OPENROUTER_KEY
    if _ZAI_KEY is not None and _DEEPSEEK_KEY is not None:
        return
    try:
        env_path = os.path.expanduser("~/AppData/Local/hermes/.env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ZAI_API_KEY=") and not line.startswith("#"):
                        _ZAI_KEY = line.split("=", 1)[1].strip().strip("'\"")
                    elif line.startswith("DEEPSEEK_API_KEY=") and not line.startswith("#"):
                        _DEEPSEEK_KEY = line.split("=", 1)[1].strip().strip("'\"")
                    elif line.startswith("OPENROUTER_API_KEY=") and not line.startswith("#"):
                        _OPENROUTER_KEY = line.split("=", 1)[1].strip().strip("'\"")
    except Exception as e:
        logger.warning("Error loading API keys: %s", e)

    # Fallback a env vars
    if not _ZAI_KEY:
        _ZAI_KEY = os.environ.get("ZAI_API_KEY", "")
    if not _DEEPSEEK_KEY:
        _DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")


def _call_chat_completions(url: str, key: str, model: str, prompt: str,
                           system_prompt: str = "") -> dict:
    """POST a un endpoint compatible con chat/completions (Z.AI o DeepSeek)."""
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
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
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


def _call_zai(prompt: str, model: str, system_prompt: str = "") -> dict:
    """Llama a Z.AI (GLM) — API compatible con chat/completions."""
    _load_keys()
    if not _ZAI_KEY:
        return {"ok": False, "error": "ZAI_API_KEY no configurada"}
    return _call_chat_completions(ZAI_URL, _ZAI_KEY, model, prompt, system_prompt)


def _call_deepseek(prompt: str, model: str, system_prompt: str = "") -> dict:
    """Llama a DeepSeek directo — API compatible con chat/completions."""
    _load_keys()
    if not _DEEPSEEK_KEY:
        return {"ok": False, "error": "DEEPSEEK_API_KEY no configurada"}
    return _call_chat_completions(DEEPSEEK_URL, _DEEPSEEK_KEY, model, prompt, system_prompt)


def _es_fallo_recuperable(err: str) -> bool:
    """True si el error de Z.AI es recuperable con fallback (rate-limit, 5xx, timeout)."""
    err_l = (err or "").lower()
    return any(m in err_l for m in (
        "429", "503", "502", "500", "rate", "limit", "quota", "timeout",
        "overloaded", "unavailable", "busy", "cloudflare", "temporarily",
    ))


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

    provider = cfg.get("provider")
    model = cfg.get("model")

    # ── deep: GLM 5.2 (Z.AI) con fallback a DeepSeek ──
    if provider == "zai":
        r = _call_zai(prompt, model, system_prompt)
        if r.get("ok"):
            r["mode"] = mode
            r["model_config"] = cfg["model"]
            r["fallback_usado"] = False
            return r
        fb_model = cfg.get("fallback_model")
        fb_provider = cfg.get("fallback_provider")
        if fb_model and fb_provider == "deepseek" and _es_fallo_recuperable(r.get("error", "")):
            logger.warning("Z.AI (%s) falló: %s → fallback DeepSeek (%s)",
                           model, r.get("error"), fb_model)
            fb = _call_deepseek(prompt, fb_model, system_prompt)
            fb["mode"] = mode
            fb["model_config"] = cfg["model"]
            fb["fallback_usado"] = True
            fb["fallback_de"] = "Z.AI→DeepSeek"
            fb["zai_error"] = r.get("error")
            return fb
        r["mode"] = mode
        r["model_config"] = cfg["model"]
        return r

    # ── fast: DeepSeek directo ──
    if provider == "deepseek":
        r = _call_deepseek(prompt, model, system_prompt)
        r["mode"] = mode
        r["model_config"] = cfg["model"]
        return r

    return {"ok": False, "error": f"Provider no soportado: {provider}"}
