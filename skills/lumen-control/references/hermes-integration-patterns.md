# Hermes Deep Integration Patterns for LUMEN

Key patterns discovered during the Hermes Agent ↔ LUMEN integration session.

## 1. Tool Override via Plugin (`override=True`)

Hermes's `registry.register()` supports `override=True`. A plugin can replace
built-in tools with LUMEN-backed handlers **without changing tool names**.

```python
# In plugin __init__.py → register(ctx):
ctx.register_tool(
    name="read_file",        # SAME name as built-in
    toolset="lumen-native",
    schema=same_as_builtin,  # Identical schema → no LLM prompt change
    handler=lumen_handler,   # Calls MCP server via LUMEN transport
    override=True,           # ← replaces built-in read_file
)
```

**Why this matters:** The LLM uses the same tool names and schemas. The
system prompt cache is preserved — critical because Hermes's design principle
is "per-conversation prompt caching is sacred."

**Discovery:** `PluginContext.register_tool()` → `registry.register(override=True)`.
MCP tools CANNOT shadow built-in tools (they're prefixed `mcp_*` and the
loader explicitly skips collisions). Only plugins with `override=True` can.

## 2. _LumenSession Pattern

A minimal MCP session wrapper that works with `LumenStdioTransport` directly,
avoiding the anyio stream bridge complexity.

```python
class _LumenSession:
    def __init__(self, transport):
        self._transport = transport
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        transport.onmessage = self._on_message

    def _on_message(self, msg):
        msg_id = msg.get("id")
        if msg_id is not None and msg_id in self._pending:
            self._pending[msg_id].set_result(msg)

    async def _rpc(self, method, params=None):
        self._next_id += 1
        msg = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        future = asyncio.get_running_loop().create_future()
        self._pending[self._next_id] = future
        await self._transport.send(msg)
        return await asyncio.wait_for(future, timeout=120)

    async def initialize(self): ...
    async def list_tools(self): ...
    async def call_tool(self, name, arguments): ...
    async def send_ping(self): ...
```

Works for: `MCPServerTask` in `mcp_tool.py`. The session is stored as
`self.session` and later used for tool calls, keepalive pings, and utility methods.

## 3. MCP Filesystem Server Pattern

A standalone MCP server (~150 lines) that replaces Hermes's built-in file tools.
The server speaks standard JSON-RPC over stdio. LUMEN compression happens at
the transport layer — the server doesn't know about it.

```python
# Minimal structure:
TOOLS = [{name, description, inputSchema}, ...]
HANDLERS = {"read_file": tool_read_file, ...}

def handle_message(msg):
    if method == "tools/call":
        result = HANDLERS[tool_name](tool_args)
        send({"jsonrpc": "2.0", "id": req_id, "result": result})

def main():
    for line in sys.stdin:
        msg = json.loads(line)
        handle_message(msg)
```

**Config in Hermes:**
```yaml
mcp_servers:
  lumen_filesystem:
    command: "python"
    args: ["server.py"]
    transport: lumen
    lumen_force_json_rpc: true
```

## 4. Architecture Decision: External Server > Plugin (Phase 0)

For the initial LUMEN integration, the external MCP server approach was chosen
over the plugin `override=True` approach because:

| Factor | External Server | Plugin Override |
|--------|----------------|-----------------|
| Risk | Zero (no Hermes changes) | Medium (touches core) |
| Tool names | `mcp_lumen_fs_read_file` | `read_file` (same) |
| Multi-agent | ✅ N agents → 1 server | ❌ Same process |
| Remote | ✅ HTTP + LUMEN | ❌ Local only |
| Portability | Any MCP client | Hermes only |

Phase 1 (plugin with `override=True`) is planned after Phase 0 validates
the performance and reliability in production.
