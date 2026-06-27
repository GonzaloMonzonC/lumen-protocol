# state_feeling — Implementación y uso

## Tool Schema

```json
{
    "name": "state_feeling",
    "description": "Externalize current cognitive state — mood, confidence, energy.",
    "inputSchema": {
        "properties": {
            "mood": {
                "type": "string",
                "enum": ["focused", "frustrated", "stuck", "tired", "confident", "curious", "overwhelmed", "neutral"]
            },
            "confidence": {"type": "integer", "minimum": 0, "maximum": 10},
            "energy": {"type": "integer", "minimum": 0, "maximum": 10},
            "context": {"type": "string", "description": "Optional context"}
        },
        "required": ["mood", "confidence", "energy"]
    }
}
```

## Server-side wiring

Para añadir un nuevo tool al thinking server, se necesitan 3 cambios en `server.py`:

### 1. Handler function (en la sección Tool implementations)

```python
def tool_state_feeling(args: dict) -> dict:
    session = _get_session(args.get("session_id"))
    mood = args["mood"]
    confidence = args.get("confidence", 5)
    energy = args.get("energy", 5)
    context = args.get("context", "")
    session.feeling = {"mood": mood, "confidence": confidence, "energy": energy, "context": context, "ts": time.time()}
    _auto_save(session)
    return {"content": [{"type": "text", "text": f"🧠 Feeling recorded: {mood} (confidence={confidence}/10, energy={energy}/10)"}]}
```

### 2. Tool schema en `TOOLS[]` (lista de schemas al inicio)

Insertar antes del `] + OBJECTIVE_SCHEMAS`. Cuidado con la coma del tool anterior — si el último tool (`wiki_list`) no tiene trailing comma, añadirla.

### 3. Mapping en `HANDLERS{}` (dict tool_name → handler)

```python
"state_feeling": tool_state_feeling,
```

### 4. Session field

```python
# __init__:
self.feeling = None

# to_dict:
"feeling": self.feeling,

# from_dict:
s.feeling = d.get("feeling", None)
```

## Uso recomendado

| Contexto | mood sugerido | confidence | energy |
|----------|--------------|------------|--------|
| Debugging largo sin éxito | frustrated | 2-4 | 3-5 |
| Después de resolver bug complejo | confident | 7-9 | 6-8 |
| Inicio de sesión, tarea clara | focused | 6-8 | 7-9 |
| Después de horas de trabajo continuo | tired | 4-6 | 2-4 |
| Explorando opciones sin dirección clara | curious | 3-5 | 5-7 |
| Múltiples tareas simultáneas | overwhelmed | 2-4 | 3-5 |
| Tarea rutinaria, sin novedades | neutral | 5-6 | 5-6 |

## Pitfalls

- `state_feeling` es VOLUNTARIO — el agente debe decidir usarlo. No hay detección automática del estado cognitivo.
- El campo `session.feeling` persiste en PDB via `_save_state()`. Sobrevive a reinicios del server.
- En el dashboard, el feeling se muestra en el panel de sesiones como `🧠 mood (C:X/10, E:Y/10)`.

## Patrón de implementación (cualquier tool nuevo)

1. Añadir schema a `TOOLS[]` (antes de `] + OBJECTIVE_SCHEMAS`)
2. Añadir handler function (antes de `HANDLERS = {`)
3. Añadir mapping a `HANDLERS{}`
4. Si el tool guarda estado: añadir field a `Session.__init__`, `to_dict()`, `from_dict()`
5. Verificar sintaxis: `py_compile.compile(server.py, doraise=True)`
6. Verificar con grep: `grep -n "tool_name" server.py` — deben aparecer schema, handler, y mapping
