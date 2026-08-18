---
name: lumen-mcp
description: "Operar y diagnosticar los MCP servers de lumen (framing, keepalive, pitfalls Windows)."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [lumen, mcp, jsonrpc, windows, troubleshooting]
    related_skills: [lumen-protocol, systematic-debugging]
---

# lumen-mcp — operación de los MCP servers de lumen

Los 4 servers MCP (`pdb`, `thinking`, `filesystem`, `web`) viven en
`implementations/mcp-servers/`. Hermes los lanza vía `config.yaml` con el
python del venv del repo.

## Regla de oro (bugs endémicos ya resueltos — commit 8d5af60)

1. **Framing**: un server lumen DEBE hablar **Content-Length framing** (MCP
   estándar), no newline-delimited. Hermes usa el SDK MCP oficial. Usar
   `lumen_mcp_stdio.py` (`read_message`/`write_message`).
2. **Keepalive**: DEBE responder a TODOS los mensajes JSON-RPC: `initialize`,
   `ping` (result `{}`), `notifications/initialized` (sin respuesta) y
   métodos desconocidos con error `-32601` (un error SÍ es una respuesta).
   El silencio = timeout = reconnect loop eterno (parking).
3. **Windows pipes**: `sys.stdin.readline()`/`read()` bloquean hasta llenar
   el buffer pedido (read del MSVCRT). Leer con **ReadFile nativo** (ctypes)
   que devuelve lo disponible — es lo que hace `lumen_mcp_stdio.py`.
4. **Handlers MCP**: el dispatcher llama SIEMPRE `handler(args_dict)`. Los
   handlers con firma posicional (`def tool_x(ns, pattern)`) fallan con
   TypeError — envolver con `_adapt_pos` (ver `pdb_watch.py`,
   `file_tools.py`, `fuzzy_search.py`).

## Diagnóstico rápido

```bash
# 1. ¿El proceso corre? (los pares venv+base son UN server: el venv es launcher)
powershell "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*lumen-protocol*mcp-servers*' } | Select-Object ProcessId,@{N='S';E={if(\$_.CommandLine -like '*thinking*'){'thinking'}elseif(\$_.CommandLine -like '*filesystem*'){'filesystem'}elseif(\$_.CommandLine -like '*web*'){'web'}else{'pdb'}}} | ft"

# 2. ¿Handshake OK? (probe del repo — lanza el server y hace initialize+list+call)
cd docs/nueva-instalacion/tests
<venv-python> mcp_probe.py <server.py> <tool> '{"args":...}'

# 3. ¿Errores de Hermes?
grep "lumen" ~/AppData/Local/hermes/logs/errors.log | tail -5
tail -30 ~/AppData/Local/hermes/logs/mcp-stderr.log

# 4. Test desde el lado Hermes
hermes mcp test <server-name>
```

## Verificación de handlers (todos los módulos)

```bash
cd implementations/mcp-servers/thinking
<venv-python> -c "
import server
rotos = [(n, str(e)[:50]) for n, h in server.HANDLERS.items()
         if (lambda: (h({}), False)[1])() is False]  # no aplica — ver nota
"
```
Nota: `h({})` con TypeError = firma rota; con KeyError/ValueError = requiere
args (correcto). Los handlers que requieren args obligatorios fallan con `{}`
— probar con args reales.

## Pitfalls

- **Los MCP cargan el código en memoria al arrancar**: un commit de rutas o
  framing NO afecta a los procesos vivos. Reiniciar: `taskkill /PID <stub>
  /T /F` — Hermes los re-lanza solo (keepalive ~1-8 min).
- **Proceso "duplicado"**: `venv\Scripts\python.exe` (stub/launcher) +
  intérprete base = UN server. No matar "el duplicado".
- **Tras reiniciar un MCP, el catálogo de tools de la sesión de Hermes queda
  desincronizado** (tools dan "not a deferrable tool"): nueva sesión o
  recargar catálogo.
- **Keepalive del thinking puede fallar por latencia** (single-threaded con
  tools pesadas: model_scan, wiki): se auto-recupera, el estado se restaura
  del PDB (PDB-first).
- **`web_extract` espera `urls` como array** (`["https://..."]`); string →
  itera por caracteres y el SSRF guard los bloquea.
- **`search_filename` (filesystem) usa regex**, no glob: `\.md$` no `*.md`.
- **Tools de thinking sin `session_id`** (thought_*, chain_diff,
  check_assumption, wiki_*) solo ven la sesión `default` — bug de diseño
  documentado, sin fix.
- **Schemas en camelCase** en thinking: `chainId`, `thoughtNumber`,
  `targetThoughts`, `nextThoughtNeeded`, `totalThoughts`.
