# 04 — Benchmark `lumen-web` (2 tools)

Fecha: 2026-08-18 · Server: `implementations/mcp-servers/web/server.py`

| # | Tool | Test | Resultado | Notas |
|---|---|---|---|---|
| 1 | `web_search` | query="lumen protocol" | ✅ | responde JSON con `results[]`; "No results" es respuesta válida (el buscador no indexa ese término) |
| 2 | `web_extract` | urls=["https://github.com/GonzaloMonzonC/lumen-protocol"], max_chars=300 | ✅ | title + content + word_count + truncated; **SSRF guard activo** (bloquea schemes no http/https) |

## Hallazgos

- `web_extract` espera **`urls` como ARRAY** (`["https://..."]`). Pasado como
  string, lo itera por caracteres y cada uno se bloquea por SSRF guard.
- Protección SSRF integrada: `Blocked: unsupported scheme ''` para URLs
  inválidas.
- Extracción real verificada: README de GitHub con word_count 2247.

## Accesibilidad desde Hermes

Tras el reinicio del server (fix de framing), el catálogo de tools de la
sesión queda desincronizado (`'mcp__lumen_web__web_search' is not a
deferrable tool`). Las tools vuelven a estar disponibles en una sesión nueva
(o tras recargar el catálogo). Verificado con `mcp_probe.py` directamente.
