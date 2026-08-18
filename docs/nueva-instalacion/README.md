# 🔬 Benchmark nueva instalación — lumen-protocol

Documentación del proceso de instalación, correcciones aplicadas y benchmark
de las tools MCP del stack LUMEN en esta máquina (Windows, usuario `gonza`).

Fecha: 2026-08-18 · Repo: `~/Documents/GitHub/lumen-protocol`

## Índice

| Doc | Contenido |
|---|---|
| [01-instalacion-y-correcciones.md](01-instalacion-y-correcciones.md) | Proceso completo de instalación + todas las correcciones históricas y las de hoy |
| [02-benchmark-filesystem.md](02-benchmark-filesystem.md) | Benchmark de las 13 tools de `lumen-filesystem` |
| [03-benchmark-thinking.md](03-benchmark-thinking.md) | Benchmark de las 81 tools de `lumen-thinking` |
| [04-benchmark-web.md](04-benchmark-web.md) | Benchmark de las 2 tools de `lumen-web` |
| [05-benchmark-mvm.md](05-benchmark-mvm.md) | Benchmark de los endpoints HTTP del MVM (`vm_api.py :8081`) |
| [06-resolucion-bug-endemico.md](06-resolucion-bug-endemico.md) | El bug endémico de los MCP duplicados/caídos: diagnóstico y fix |

## Resumen de estado (18/08)

| Componente | Estado | Notas |
|---|---|---|
| `lumen-filesystem` MCP | ✅ operativo | 13 tools |
| `lumen-thinking` MCP | ✅ operativo (tras reinicio) | 81 tools |
| `lumen-web` MCP | ✅ operativo (tras reinicio) | 2 tools |
| `lumen-pdb` MCP | ✅ operativo (tras fix `ping`) | 19 tools |
| `vm_api.py` (MVM :8081) | ✅ operativo | health + ejecución M + DDP |
| BD canónica | ✅ `implementations/mcp-servers/pdb/lumen-pdb.db` | WAL, 729 KB |

## Artefactos de prueba

- `tests/mcp_probe.py` — cliente MCP stdio (transporte lumen newline-JSON) para
  testear un server sin pasar por Hermes. Uso:
  `python mcp_probe.py <server.py> <tool_name> '{"args": ...}'`
  ⚠️ Requiere `PYTHONUNBUFFERED=1` en el entorno (buffering de stdin en pipes).
- `tests/` — archivos de prueba para el benchmark de filesystem.

## Aprendizajes clave

1. **Los procesos python "duplicados" NO son instancias duplicadas**: en
   Windows, `venv\Scripts\python.exe` es un launcher que ejecuta el Python base
   como proceso hijo. `tasklist` muestra ambos — es UN solo server.
2. **El transporte MCP de lumen es newline-delimited JSON**, no Content-Length
   framing. Un cliente estándar MCP (framing LSP) no recibe respuesta.
3. **Los servers MCP lumen deben responder a TODO método** (incluido `ping` y
   desconocidos) o el keepalive de Hermes hace timeout → reconnect loop eterno.
4. **Los MCP servers cargan el código en memoria al arrancar**: si el proceso
   lleva vivo desde antes de un commit de rutas, sigue usando las rutas viejas
   hasta reiniciarlo.
