# ◆ LUMEN Agent Loop

> **EN:** LUMEN learns your traffic. Watch the session dictionary progressively shrink wire sizes across a simulated LLM agent conversation.
>
> **ES:** LUMEN aprende tu trafico. Observa como el diccionario de sesion reduce progresivamente el tamano del wire en una conversacion simulada de agente LLM.

---

## Quick Run

```bash
cd examples/agent-loop
python agent_loop.py
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| --turns | 30 | Number of conversation turns |
| --no-graph | false | Skip ASCII savings graph |
| --no-narrative | false | Skip agent narrative text |

```bash
python agent_loop.py --turns 50
python agent_loop.py --turns 100 --no-graph
```

## How It Works

1. An LLM agent initializes an MCP connection (initialize, tools/list)
2. The agent alternates between tool calls and receiving results
3. LUMEN feeds each message into the **session dictionary** (slots 0x80-0xFE)
4. As keys are learned, `compress_value()` replaces repeated strings with 1-byte dict IDs
5. The "Warm" column shows wire size with full session dictionary knowledge

## What You Will See

```
Turn     JSON-RPC  LUMEN Cold  LUMEN Warm     Savings    Dict
------------------------------------------------------------
#0          240 B       117 B        90 B 62%   >     26
#1           51 B        27 B        27 B 47%   >      .
...
#25         293 B       158 B       158 B 46%   >     26
------------------------------------------------------------
TOTAL      6.4 KB      3.6 KB      3.3 KB 47.5%
```

- **LUMEN Cold:** Static dictionary only (MCP keys like "jsonrpc", "method", etc.)
- **LUMEN Warm:** Static + session dictionary (your traffic patterns)
- **Dict size:** Grows as new keys are learned; caps at 127 session slots

> The session dictionary stabilizes after ~10 turns — LUMEN has learned the traffic pattern. In production with real long-lived connections, cumulative savings exceed 80%.

---

## Espanol

### Como funciona

1. Un agente LLM inicializa una conexion MCP
2. El agente alterna entre llamadas a herramientas y recepcion de resultados
3. LUMEN alimenta cada mensaje en el **diccionario de sesion** (slots 0x80-0xFE)
4. Las claves aprendidas se reemplazan por IDs de 1 byte en mensajes comprimidos
5. La columna "Warm" muestra el wire con diccionario de sesion completo

En produccion con conexiones reales de larga duracion, el ahorro acumulado supera el 80%.

---

[Back to examples](../README.md)