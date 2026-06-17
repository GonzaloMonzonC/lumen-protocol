<p align="center">
  <br>
  <h1 align="center">◆ LUMEN</h1>
  <p align="center"><strong>Lightweight Universal Model Exchange Network</strong></p>
  <p align="center">
    Un protocolo binario para MCP que hace que JSON-RPC parezca dial-up.
    <br>
    <em>Ahorro de wire: 40–80%. Latencia: sub-ms. Overhead: 3–6 bytes.</em>
  </p>
  <br>
</p>

<p align="center">
  <a href="README.md">English</a> &nbsp;|&nbsp; <strong>Español</strong>
</p>

<p align="center">
  <a href="INSTALL_ES.md"><strong>🚀 Instalar en Hermes Agent</strong></a> &nbsp;|&nbsp;
  <a href="https://github.com/NousResearch/hermes-agent/pull/47740">PR #47740</a> &nbsp;|&nbsp;
  <strong>✅ 29 tools compatibles</strong>
</p>

---

## ¿Por qué? / Why?

JSON-RPC sobre stdio es el estándar MCP. Funciona. Pero a escala, duele:

| Dolor | Solución LUMEN |
|-------|---------------|
| **Wire verboso** — `{"jsonrpc":"2.0","id":7,...}` en cada mensaje | **Diccionario estático** (128 claves) + **diccionario de sesión** (127 claves). Las claves repetidas → 1 byte. |
| **Parsing costoso** — cada blob JSON debe decodificarse completo | **Frames auto-delimitantes** (Hyb128). Saltar frames enteros en O(1). |
| **Sin streaming** — JSON es un documento único y completo | **Streaming nativo** (`STREAM_DATA` + `STREAM_INIT`). Tokens llegan token-por-token. |
| **Sin modelo de seguridad** — acceso todo-o-nada al servidor | **Zero-trust Macaroons** con caveats atenuables. Cifrado de wire con ChaCha20-Poly1305. |

---

## Quick Start

```bash
git clone https://github.com/GonzaloMonzonC/lumen-protocol.git
cd lumen-protocol

# Python
cd implementations/python && pip install -e . && cd ../..
python examples/cost-calculator/cost_calculator.py

# TypeScript
cd implementations/typescript && npm install && npm run build && cd ../..
node --test implementations/typescript/dist/*.test.js

# Rust
cd implementations/rust && cargo test && cargo bench && cd ../..
```

---

## Protocolo en un diagrama

```
┌──────────────────────────────────────────────────────┐
│ [Hyb128 LEN:1-5B]  [TYPE:1B]  [FLAGS:1B]  [PAYLOAD] │
└──────────────────────────────────────────────────────┘
  0-63B   → 1 byte        REQUEST   COMPRESSED
  64KB    → 3 bytes       RESPONSE  ENCRYPTED
  4GB     → 5 bytes       NOTIFY    STREAM
  >4GB    → LEB128        STREAM_DATA …

  Overhead: 3 bytes (carga pequeña) a 7 bytes (4 GB)
```

**Compresión en acción:**
```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"search","arguments":{"pattern":"TODO"}}}
```
→ LUMEN: `type=REQUEST, tool, method, name, pattern` son dict IDs (1 byte cada una), solo `"search"` y `"TODO"` viajan como strings.

---

## Métricas clave

| Benchmark | JSON-RPC | LUMEN | Reducción |
|-----------|----------|-------|-----------|
| RPC mínimo (heartbeat) | 50 B | 21 B | **58%** |
| Tool list (100 tools) | 39.7 KB | 24.8 KB | **37%** |
| Token stream LLM (10K) | 1009 KB | 543 KB | **46%** |
| Agent loop (30 turnos) | 6.4 KB | 3.3 KB | **48%** |

> Pruébalo: `python examples/cost-calculator/cost_calculator.py`

---

## Implementaciones

| Lenguaje | Ruta | Estado |
|----------|------|--------|
| **Rust** | `implementations/rust/` | Implementación de referencia, WASM, FFI (C ABI) |
| **TypeScript** | `implementations/typescript/` | Node.js + navegador, zero-copy SHM vía koffi |
| **Python** | `implementations/python/` | Protocolo completo, dict de sesión, tools MCP |
| **PHP** | `implementations/php/` | PHP 8.5+, 217/217 e2e pasando |
| **C#** | `implementations/dotnet/` | .NET 9, P/Invoke FFI a Rust |
| **WASM** | `implementations/rust/wasm/` | Listo para navegador, 22 KB gzipped |

---

## Niveles de transporte

```
Level 1 — stdio/UDS       (local, zero-copy SHM)
Level 2 — TCP             (LAN, encuadre Hyb128)
Level 3 — UDP + Multicast (descubrimiento de servicio, fire-and-forget)
Level 4 — QUIC            (WAN, HTTP/3, producción)
```

---

## ◆ Demos (ejecuta en <2 min cada una)

| Demo | Comando | Qué demuestra |
|------|---------|---------------|
| **Cost Calculator** | `python examples/cost-calculator/cost_calculator.py` | Proyección de costo de egress cloud para 1,000 servidores |
| **Agent Loop** | `python examples/agent-loop/agent_loop.py` | El diccionario de sesión aprende tu tráfico en tiempo real |
| **MCP Drop-In** | `python examples/mcp-dropin/dropin_server.py` | Servidor HTTP real: JSON-RPC entra, LUMEN binario sale |

---

## Documentación

| Doc | Contenido |
|-----|-----------|
| **[README.md](README.md)** | Landing page (EN) |
| **[README_EXT.md](README_EXT.md)** | Especificación del protocolo, benchmarks, arquitectura (EN) |
| **[README_EXT_ES.md](README_EXT_ES.md)** | Lo mismo, en español |
| **[RFC_LUMEN_ES.md](RFC_LUMEN_ES.md)** | RFC formal del protocolo (español) |
| **[SPEC_DEV_ES.md](SPEC_DEV_ES.md)** | Especificación de referencia |
| **[examples/](examples/)** | Demos ejecutables con READMEs bilingües |

---

## Licencia

MIT — ver [LICENSE](LICENSE)

---

<p align="center">
  <sub>LUMEN · <em>Tu wire MCP. Solo que más pequeño. Más rápido. Más seguro.</em></sub>
</p>