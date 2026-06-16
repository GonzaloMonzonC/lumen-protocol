# STRATEGIC PLAN: LUMEN Ecosystem Evolution

## Current State

```
Hermes Agent --JSON-RPC/stdio--> cadencia-mcp --HTTP/REST--> cadences-gateway
                                    (MCP Server)               (OpenAI API)
                                                                 |
                                                     DeepSeek/Groq/Gemini/...
```

## Target Architecture

```
Hermes Agent --HTTP/OpenAI--> cadences-gateway --LUMEN/stdio--> cadencia-mcp
                |                                                    |
           (opt LUMEN)                                      MCP Clients (Copilot)
```

## Phases

### Phase 1: LUMEN between cadencia-mcp <-> cadences-gateway
- cadences-gateway: LUMEN transport listener (TypeScript)
- cadencia-mcp: replace HTTP fetch() with LUMEN frames
- Benefits: STREAM_DATA for LLM tokens, MUX for concurrency, Macaroons for auth

### Phase 2: Hermes direct to cadences-gateway
- Option A (quick): OpenAI API as `provider: custom` in Hermes
- Option B (future): MCP endpoint with LUMEN on cadences-gateway

### Phase 3: LUMEN-aware OpenAI API
- Content negotiation: Accept: application/lumen+binary
- Backward compatible, drop-in for any OpenAI client

## Priorities
1. Verify cadences-gateway OpenAI API works with Hermes
2. cadences-gateway LUMEN listener (TypeScript)
3. cadencia-mcp LUMEN transport
4. cadences-gateway MCP endpoint
5. Hermes direct provider (OpenAI first, LUMEN later)
