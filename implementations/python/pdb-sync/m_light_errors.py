"""
m_light_errors.py — Error handling pattern del compilador MSM adaptado a M-Light.

MSM (FUN_0043eac0, 1.642 instr):
  - Error counts por tipo
  - Thresholds configurables (fatal tras N errores)
  - Cleanup contextual en fatales
  - Logging de errores con contexto

PDB:
  - Error levels: FATAL, ERROR, WARNING, INFO
  - Error counters en ^System("errors","m_light")
  - Callbacks on_error para manejo externo
"""

import sys, os, traceback
from datetime import datetime, timezone

# ── Error levels (MSM: severity bits) ──
FATAL   = 4
ERROR   = 3
WARNING = 2
INFO    = 1

LEVEL_NAMES = {
    FATAL: "FATAL",
    ERROR: "ERROR",
    WARNING: "WARNING",
    INFO: "INFO",
}

class MLErrorHandler:
    """Error handler para M-Light (MSM FUN_0043eac0 pattern).
    
    Características:
    - Límite de errores por tipo (threshold)
    - Callback on_error para logging externo
    - Contexto de ejecución para mensajes descriptivos
    - Persistencia opcional en PDB
    """
    
    def __init__(self, name="m_light", thresholds=None):
        self.name = name
        self.counts = {FATAL: 0, ERROR: 0, WARNING: 0, INFO: 0}
        # MSM: thresholds desde config
        self.thresholds = thresholds or {FATAL: 1, ERROR: 10, WARNING: 50}
        self.on_error = None  # callback(msg, level, ctx)
        self.context = {}     # contexto de ejecución actual
        self.halted = False
    
    def set_context(self, **kwargs):
        """Establecer contexto de ejecución (MSM: iVar2 context struct)."""
        self.context.update(kwargs)
    
    def error(self, msg, level=ERROR, exc_info=False):
        """Registrar un error (MSM: FUN_0043eac0 call).
        
        Returns: True si es fatal/grave, False si es warning
        """
        self.counts[level] += 1
        threshold = self.thresholds.get(level, 999)
        
        ctx_str = " | ".join(f"{k}={v}" for k, v in self.context.items())
        full_msg = f"[{LEVEL_NAMES.get(level, '?')}] {msg}"
        if ctx_str:
            full_msg += f" (ctx: {ctx_str})"
        
        if exc_info:
            full_msg += f"\n{traceback.format_exc()}"
        
        # Callback (MSM: log a ^LOG o lo que toque)
        if self.on_error:
            self.on_error(full_msg, level, dict(self.context))
        
        # Threshold check (MSM: if count > threshold → halt)
        if self.counts[level] >= threshold and level >= ERROR:
            self.halted = True
            fatal_msg = f"[FATAL] Error threshold reached: {self.counts[level]} {LEVEL_NAMES[level]} errors"
            if self.on_error:
                self.on_error(fatal_msg, FATAL, dict(self.context))
            return True
        
        return level >= ERROR
    
    def reset(self):
        """Resetear contadores (MSM: new context/scope)."""
        self.counts = {FATAL: 0, ERROR: 0, WARNING: 0, INFO: 0}
        self.halted = False
        self.context = {}
    
    def summary(self):
        """Resumen de errores."""
        return {
            "name": self.name,
            "counts": self.counts.copy(),
            "thresholds": self.thresholds.copy(),
            "halted": self.halted,
        }


# ── PDB persistence ──

def _get_tools():
    pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get
    return tool_set, tool_get

def persist_errors(handler, session_id=None):
    """Guardar contadores en PDB (MSM: ^System("errors"))."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sid = session_id or "default"
    ts_set, _ = _get_tools()
    
    for level, count in handler.counts.items():
        if count > 0:
            ts_set({"ns": "System", "subs": ["errors", "m_light", sid, LEVEL_NAMES[level], ts],
                    "value": {"count": count, "threshold": handler.thresholds.get(level)}})


# ── Integration with M-Light ──

# Instancia global (MSM: error handler singleton)
ERROR_HANDLER = MLErrorHandler()
