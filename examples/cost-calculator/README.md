# ◆ LUMEN Cost Calculator

> **EN:** How much is JSON-RPC costing your infrastructure? Simulate real MCP workloads, measure wire sizes, and project annual cloud egress savings with LUMEN.
>
> **ES:** ¿Cuánto te está costando JSON-RPC en infraestructura? Simula cargas MCP reales, mide tamaños de wire y proyecta ahorros anuales de egress con LUMEN.

---

## Quick Run

```bash
cd examples/cost-calculator
python cost_calculator.py
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--monthly-calls` | `10M` | Monthly MCP calls (e.g. `5M`, `500K`, `1B`) |
| `--egress-cost` | `0.09` | Cloud egress cost per GB (AWS/GCP std: $0.09) |
| `--csv` | _(none)_ | Export results to CSV file |

```bash
python cost_calculator.py --monthly-calls 50M --egress-cost 0.12 --csv results.csv
```

## Scenarios Simulated

| # | Scenario | What it measures |
|---|----------|-----------------|
| 1 | `tools/list` (100 tools) | Tool registry listing — structured JSON with `inputSchema` |
| 2 | `tools/list` (500 tools) | Large tool registry — scaling behavior |
| 3 | `file_context` (50 files × 100KB) | Source code payloads — LUMEN compresses structure, not content |
| 4 | `token_stream` (10K tokens) | LLM token streaming — repeated `{"delta":"word"}` patterns |
| 5 | `multi_agent` (10 agents × 100 reqs) | Multi-agent tool calls — high fan-out |
| 6 | `heartbeat` | Minimal ping — overhead comparison |

## Expected Output

```
╔═════════════════════════════════════════════════════════════════════╗
║                    LUMEN Protocol — Wire Size Comparison           ║
╠═════════════════════════════════════════════════════════════════════╣
║ tools/list (100 tools)                39.7 KB    24.8 KB    37.5%  ║
║ tools/list (500 tools)               199.2 KB   124.9 KB    37.3%  ║
║ file_context (50 files × 100KB)       5.07 MB    4.89 MB     3.6%  ║
║ token_stream (10K tokens)           1009.6 KB   543.7 KB    46.2%  ║
║ multi_agent (10 agents × 100 reqs)   193.8 KB   111.1 KB    42.7%  ║
║ heartbeat (single ping)                  50 B       21 B    58.0%  ║
╠═════════════════════════════════════════════════════════════════════╣
║ AGGREGATE                              6.48 MB    5.67 MB    12.4%  ║
╚═════════════════════════════════════════════════════════════════════╝

Annual savings for 1,000 servers: $1.41M
```

> **Note:** The `file_context` scenario (3.6%) drags the aggregate down — LUMEN compresses structural keys, not source code text. In agent-loop scenarios (demo #2), the session dictionary pushes savings above 80%.

---

## Español

### Escenarios simulados

| # | Escenario | Qué mide |
|---|-----------|----------|
| 1 | `tools/list` (100 tools) | Listado de herramientas MCP con `inputSchema` |
| 2 | `tools/list` (500 tools) | Escalado a 500 herramientas |
| 3 | `file_context` (50 archivos × 100KB) | Código fuente — LUMEN comprime estructura, no contenido |
| 4 | `token_stream` (10K tokens) | Streaming de tokens LLM |
| 5 | `multi_agent` (10 agentes × 100 reqs) | Llamadas multi-agente |
| 6 | `heartbeat` | Ping mínimo — comparación de overhead |

### Proyección de costos

El proyector calcula el **costo anual de egress** para 50, 200 y 1,000 servidores basándose en el ahorro promedio y el costo por GB que especifiques.

```bash
python cost_calculator.py --monthly-calls 20M --egress-cost 0.09
```

---

