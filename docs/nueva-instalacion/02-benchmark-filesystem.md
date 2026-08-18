# 02 — Benchmark `lumen-filesystem` (13 tools)

Fecha: 2026-08-18 · Server: `implementations/mcp-servers/filesystem/server.py`
· Entorno de prueba: `docs/nueva-instalacion/tests/` (creado para el test).

## Resultado global

| Resultado | Tools |
|---|---|
| ✅ OK | 13 / 13 |
| ⚠️ Errores de uso (no bugs) | `search_filename` con glob en vez de regex |

## Detalle por tool

| # | Tool | Test | Resultado | Notas |
|---|---|---|---|---|
| 1 | `server_stats` | sin args | ✅ | uptime 3h21m, 13 tools, 68 requests |
| 2 | `disk_usage` | path=tests | ✅ | 346 B, 2 files, 1 subdir (recursivo) |
| 3 | `file_info` | path=sample.txt | ✅ | tamaño, fechas, permisos, **encoding utf-8** |
| 4 | `list_directory` | path=tests | ✅ | `[FILE] sample.txt (241B)` / `[DIR] subdir` |
| 5 | `read_file` | path=sample.txt | ✅ | líneas numeradas `1\|...` |
| 6 | `read_files` | paths=[2 archivos] | ✅ | multi-archivo con separadores `=== path ===` |
| 7 | `search_filename` | pattern=`*.md` | ⚠️→✅ | **espera REGEX, no glob**; con `\.md$` → encontró `subdir/nota.md` |
| 8 | `search_files` | pattern=`ZORRO` | ✅ | encontró 2 coincidencias en 2 archivos (recursivo) |
| 9 | `search_with_context` | pattern=`ZORRO`, context=1 | ✅ | contexto `>>>` alrededor del match |
| 10 | `stream_read` | chunk 1/1 | ✅ | `[FINAL CHUNK]` — paginación por chunks |
| 11 | `patch` | replace `ZORRO-ROJO-42` | ✅ | `Replaced 1 occurrence(s)` |
| 12 | `write_file` | path=escrito_via_mcp.md | ✅ | `Wrote 108 bytes` |
| 13 | `find_duplicates` | path=tests | ✅ | detectó grupo duplicado (105 B, 2 copias). ⚠️ 1er intento falló por secuencia del test (el archivo copiado se modificó antes del scan) |

## Hallazgos

- **`search_filename` usa regex** (ripgrep-style), no globs: `*.md` da
  `Invalid regex pattern`. Usar `\.md$`.
- `disk_usage`/`find_duplicates` **saltan directorios ignorados** (gitignore).
- `find_duplicates` hashea solo archivos con colisión de tamaño (eficiente).
- `file_info` detecta encoding (útil en Windows donde el shell miente).
- Las escrituras (patch/write_file) devuelven confirmación con conteo.

## Tiempos (aproximados, vía MCP local)

Todas las tools respondieron en < 500 ms (server local, SQLite/paths en
memoria). El primer arranque del server tarda lo que tarde el import de
dependencias.
