# 06 — Bug endémico: MCP duplicados / reconnect loop — diagnóstico y fix

## Síntoma

- `lumen-pdb` reiniciándose cada ~8.5 min toda la noche (35+ intentos en
  `mcp-stderr.log`): `keepalive failed → 5 reconnects → parking`.
- Tools de `lumen-thinking` que tocan la BD fallaban con `unable to open
  database file` aunque la BD canónica abría bien por CLI.
- `tasklist` mostraba cada server MCP "duplicado" (venv + Python312).

## Causas raíz (2 bugs reales, independientes)

### 1. `lumen-pdb` no respondía al keepalive → reconnect loop eterno

`pdb/server.py` solo manejaba `initialize`/`tools/list`/`tools/call` y
**tragaba en silencio** los métodos desconocidos (`except: pass`). El
keepalive de Hermes (método `ping`) nunca recibía respuesta → timeout →
reconnect → parking. El server de thinking respondía a TODO método
desconocido con error JSON-RPC `-32601` → Hermes lo consideraba vivo.

**Fix**: manejar `ping` (result `{}`), `notifications/initialized` (sin
respuesta) y responder a desconocidos con `-32601`.

### 2. Los servers hablaban newline-JSON; Hermes habla Content-Length

Los servers lumen leían `sys.stdin.readline()` (newline-delimited) pero el
cliente MCP de Hermes usa el **SDK MCP oficial con framing Content-Length**.
Funcionaba "de milagro" (el body JSON del handshake, >8 KB, desbloqueaba el
readline), pero cualquier mensaje pequeño aislado era frágil.

**Fix**: nuevo módulo compartido `implementations/mcp-servers/
lumen_mcp_stdio.py` con `read_message()`/`write_message()` (framing
Content-Length + ReadFile nativo vía ctypes — el `read()` del MSVCRT en
pipes de Windows bloquea hasta llenar el buffer pedido). Aplicado a los 4
servers (pdb, thinking, filesystem, web).

### Hallazgo adicional (falso positivo)

Los pares de procesos python (venv + Python312) NO son instancias
duplicadas: en Windows `venv\Scripts\python.exe` es un launcher que exec el
intérprete base como hijo. UN solo server por servicio.

### Diagnóstico que costó (lección para el próximo)

`mcp_probe.py` (cliente de prueba) también usaba `read()` del MSVCRT para
leer las respuestas → no veía respuestas pequeñas → parecía que los servers
no respondían. El bug estaba en el probe, no en los servers. Lección: **en
Windows, los pipes con Python `read()`/`readline()` bloquean hasta llenar el
buffer; usar ReadFile nativo (ctypes) para leer lo disponible**.

## Estado final (verificado)

- 4 servers MCP corriendo con el framing correcto, respondiendo a
  `initialize`/`ping`/`tools/list`/`tools/call`/desconocidos.
- `hermes mcp test lumen-pdb` → 19 tools OK. Probe → INIT/TOOLS/CALL OK.
- `lumen-thinking` restaura estado desde la BD canónica al arrancar.

## Regla de oro

> Un server MCP de lumen debe: (1) hablar **Content-Length framing** (no
> newline), (2) responder a **todos** los métodos (`ping` incluido; los
> desconocidos con error `-32601` que SÍ es una respuesta), (3) leer stdin
> con **ReadFile nativo** si corre en Windows.
