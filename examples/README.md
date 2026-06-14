> **`examples/`** — Demos ready to run. Each demo is self-contained and demonstrates a different dimension of LUMEN's value proposition.

---

## ◆ Demos

| # | Demo | Audience | Pitch | Time |
|---|------|----------|-------|------|
| 1 | **[`cost-calculator`](cost-calculator/)** | CTO, VP Eng | ¿Cuánto te cuesta JSON-RPC en cloud egress? | 2 min |
| 2 | **[`agent-loop`](agent-loop/)** | Tech Lead, Architect | El diccionario de sesión aprende tu tráfico | 1 min |
| 3 | **[`mcp-dropin`](mcp-dropin/)** | Developer, SRE | Tu server MCP, nuestro wire. Cero cambios. | 3 min |

---

## ◆ Quick Start

```bash
# Install LUMEN first
cd implementations/python && pip install -e . && cd ../..

# Demo 1 — Cost projection
python examples/cost-calculator/cost_calculator.py

# Demo 2 — Session dictionary in action
python examples/agent-loop/agent_loop.py --turns 30

# Demo 3 — Live MCP server with LUMEN binary responses
python examples/mcp-dropin/dropin_server.py
# Then open http://localhost:9090/ in your browser
```

---

## ◆ Demo Details

### 1. Cost Calculator
Simulates real MCP payloads: `tools/list`, `file_context`, `token_stream`, `multi_agent`, `heartbeat`. Compares JSON-RPC vs LUMEN wire sizes and projects **annual cloud egress cost** for 50, 200, or 1,000 servers.

```bash
python examples/cost-calculator/cost_calculator.py \
  --monthly-calls 10M \
  --egress-cost 0.09 \
  --csv results.csv
```

### 2. Agent Loop
A simulated LLM agent calling MCP tools across a conversation. Shows how the **LUMEN session dictionary** learns repeated key patterns and progressively shrinks wire size with every message — *it gets better the more you use it.*

```bash
python examples/agent-loop/agent_loop.py --turns 50
# Or without ASCII graph:
python examples/agent-loop/agent_loop.py --turns 30 --no-graph
```

### 3. MCP Drop-In Server
A production-style HTTP server with real MCP tools (`echo`, `get_time`, `file_info`, `search_code`, `get_health`). Clients send standard JSON-RPC; the server can respond in **JSON-RPC** or **LUMEN binary** — toggle with `?lumen=1`. Includes a live dashboard at `/`.

```bash
python examples/mcp-dropin/dropin_server.py --port 9090

# JSON-RPC response:
curl -X POST http://localhost:9090/rpc \
  -H "Content-Type: application/json" \
  -d ""{"jsonrpc":"2.0","id":1,"method":"tools/list"}""

# LUMEN binary response (40% smaller):
curl -X POST "http://localhost:9090/rpc?lumen=1" \
  -H "Content-Type: application/json" \
  -o response.bin \
  -d ""{"jsonrpc":"2.0","id":1,"method":"tools/list"}""
```

---

## ◆ Requirements

- Python 3.10+
- LUMEN Python package: `pip install -e implementations/python`
- `curl` (optional, for MCP drop-in testing)

---

## ◆ File Structure

```
examples/
├── README.md                  ← This file
├── cost-calculator/
│   ├── README.md
│   └── cost_calculator.py
├── agent-loop/
│   ├── README.md
│   └── agent_loop.py
└── mcp-dropin/
    ├── README.md
    └── dropin_server.py
```

---

## ◆ Español (Spanish)

Las demos están documentadas en inglés y español. Cada demo tiene su propio `README.md` bilingüe.

| Demo | Español |
|------|---------|
| `cost-calculator` | Simula payloads MCP reales, compara tamaños JSON-RPC vs LUMEN y proyecta el **costo anual de egress** en la nube. |
| `agent-loop` | Un agente LLM simulado llamando herramientas MCP. Muestra cómo el **diccionario de sesión** de LUMEN aprende patrones de claves y reduce el wire progresivamente. |
| `mcp-dropin` | Un servidor HTTP MCP real. Los clientes envían JSON-RPC estándar; el servidor responde en **JSON o LUMEN binario** según el query param `?lumen=1`. Incluye dashboard en vivo. |

---

**[↑ Back to main README](../README.md)**
