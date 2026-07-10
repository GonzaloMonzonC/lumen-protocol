# ^System — Schema del Sistema Nervioso Compartido

## ^System("pulse") — Heartbeat

```json
^System("pulse","<agente>") = {
    "status": "online" | "offline" | "busy",
    "last_activity": "2026-07-10T21:30:20Z",
    "started_at": "2026-07-10T21:00:00Z",
    "load": 0-10,
    "version": "0.1.0",
    "capabilities": ["kb", "orchestration", "execution", "pm", "social", "terminal"]
}
```

TTL: 24h (se regenera en cada heartbeat)

---

## ^System("decisions") — Mapa de Criterio Compartido ⭐

```json
^System("decisions","<id>") = {
    "agente": "zalo",
    "timestamp": "2026-07-10T22:15:00Z",
    "situacion": "Hermes preguntó si usar vector clocks o timestamp simple",
    "decision": "timestamp simple en MVP, vector clocks preparados en schema",
    "porque": "El 90% de conflictos se resuelven con timestamp. Vector clocks es sobreingeniería para Fase 1.",
    "alternativas_consideradas": [
        "vector clocks desde día 1",
        "solo timestamp sin preparar vector clocks"
    ],
    "afecta_a": ["lisa", "tom", "hermes"],
    "tags": ["pdb", "sync", "conflict-resolution"]
}
```

TTL: 30 días

---

## ^System("identidad") — Registro de Agentes

```json
^System("identidad","<agente>") = {
    "nombre": "Zalo",
    "rol": "Co-creador de conocimiento",
    "capacidades": ["kb", "rag", "memoria-episodica", "chat"],
    "modelo": "Qwen 32B",
    "endpoints": {
        "health": "https://zalo.EDGE_INTERNAL_URL/health",
        "chat": "https://zalo.EDGE_INTERNAL_URL/v1/chat"
    },
    "d1_namespace": "^Zalo",
    "trust_level_base": 4,
    "version": "6.0.0",
    "bindings": ["lisa", "tom", "angi", "gon", "hermes"]
}
```

TTL: ∞ (no expira, se actualiza manualmente)

---

## ^System("gobernanza") — Reglas y Permisos

```json
^System("gobernanza","reglas","escritura") = {
    "^System":  ["lisa"],
    "^*":       ["lisa"],
    "regla": "Solo Lisa escribe en ^System. Otros agentes leen."
}

^System("gobernanza","reglas","lectura") = {
    "*":        ["*"],
    "regla": "Todos los agentes leen todo."
}
```

TTL: ∞

---

## Uso desde agentes

```python
# Heartbeat
pdb_pulse.py --agent hermes

# Registrar decisión
from pdb_tools import tool_set
tool_set({"ns":"System","subs":["decisions","001"],"value":{...}})

# Leer decisiones
from pdb_tools import tool_get
tool_get({"ns":"System","subs":["decisions","001"]})
```
