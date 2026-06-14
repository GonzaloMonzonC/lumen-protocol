# ◆ LUMEN MCP Drop-In Server

> **EN:** Your MCP server. Our wire. Zero code changes. A production-style HTTP server that demonstrates LUMEN as a transparent wire-format upgrade.
>
> **ES:** Tu servidor MCP. Nuestro wire. Cero cambios. Un servidor HTTP estilo produccion que demuestra LUMEN como mejora transparente del formato de wire.

---

## Quick Run

```bash
cd examples/mcp-dropin
python dropin_server.py
# Open http://localhost:9090/ in your browser
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| --port | 9090 | HTTP server port |

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | / | Live dashboard with wire statistics and bar chart |
| GET | /stats | JSON stats (requests, JSON bytes, LUMEN bytes, savings) |
| POST | /rpc | Standard MCP JSON-RPC endpoint |
| POST | /rpc?lumen=1 | JSON-RPC in, LUMEN binary out |

## Tools

| Tool | Description |
|------|-------------|
| echo | Echo back the input message |
| get_time | Current server time (ISO 8601) |
| file_info | File metadata (simulated) |
| search_code | Code search with pattern matching (simulated) |
| get_health | Server health + wire statistics |

## Testing

```bash
# JSON-RPC response (standard)
curl -s -X POST http://localhost:9090/rpc \
  -H "Content-Type: application/json" \
  -d "{"jsonrpc":"2.0","id":1,"method":"tools/list"}"

# LUMEN binary response (~40% smaller)
curl -s -X POST "http://localhost:9090/rpc?lumen=1" \
  -H "Content-Type: application/json" \
  -o response.bin \
  -d "{"jsonrpc":"2.0","id":1,"method":"tools/list"}"

# Check stats
curl -s http://localhost:9090/stats | python -m json.tool
```

## Architecture

```
Client (JSON-RPC) → HTTP POST /rpc?lumen=1
                    ↓
              dropin_server.py
              ┌──────────────┐
              │ handle_mcp() │ → tool execution
              └──────┬───────┘
                     ↓
              compress_value()
                     ↓
              build_frame() → binary LUMEN frame
                     ↓
              HTTP 200
              Content-Type: application/lumen+binary
              X-Lumen-Compressed: true
```

- Content negotiation via query param: no special headers required
- Works with any existing MCP client that supports HTTP transport
- LUMEN binary responses include `Content-Type: application/lumen+binary`
- Dashboard auto-refreshes every 2s showing live wire comparison

---

## Espanol

### Endpoints

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | / | Dashboard en vivo con estadisticas de wire |
| GET | /stats | Estadisticas JSON |
| POST | /rpc | JSON-RPC estandar |
| POST | /rpc?lumen=1 | JSON-RPC entra, LUMEN binario sale |

El dashboard muestra una comparacion visual en tiempo real del tamano de cada respuesta en JSON vs LUMEN, con barras apiladas y ahorro porcentual acumulado.

---

[Back to examples](../README.md)