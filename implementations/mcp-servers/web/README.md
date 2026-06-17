# LUMEN Web Search + Extract Server

Unified search + extraction in a single MCP call. Zero API keys required.

## Why this over Hermes built-in?

| Feature | Hermes (Firecrawl) | LUMEN Web |
|---------|-------------------|-----------|
| Search quality | ✅ Professional | ⚖️ DuckDuckGo API |
| Extract quality | ✅ AI-powered | Basic HTML→text |
| Search + extract in 1 call | ❌ 2 separate calls | ✅ unified |
| API key required | ✅ (Nous subscription) | ❌ none |
| Multi-agent cache | ❌ | ✅ shared cache |
| Wire savings | N/A | 40-50% via LUMEN |

**LUMEN Web is for fast, free, unified search+extract.** Hermes Firecrawl is for professional extraction quality. They complement each other.

## Tools

| Tool | Description |
|------|-------------|
| `web_search` | Search DuckDuckGo. Returns structured results (title, URL, description). Optional auto-extraction of top results. |
| `web_extract` | Extract web pages as simplified markdown text. Max 5 URLs per call. |

## Quick Start

```bash
python server.py
```

## Hermes Config

```yaml
mcp_servers:
  lumen_web:
    command: "python"
    args: ["implementations/mcp-servers/web/server.py"]
    transport: lumen
    lumen_force_json_rpc: true
```

## Example

```python
# Search + auto-extract top 2 results in ONE call
web_search("LUMEN protocol", limit=5, extract_top=2)
# → returns: [results] + [extracted_content]
```
