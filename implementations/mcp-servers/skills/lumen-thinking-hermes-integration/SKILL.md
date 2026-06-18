---
name: lumen-thinking-hermes-integration
description: Deep integration guide for Lumen Thinking in Hermes Agent — hooks, plugins, config, subagent usage. Activates the cognitive layer natively.
version: 1.0.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, thinking, hermes, integration, plugin]
---

# Lumen Thinking — Hermes Deep Integration

How to connect Lumen Thinking's 22 cognitive tools as a native Hermes cognitive
layer. Beyond "MCP server configured" — this is **activation as infrastructure**.

---

## Phase 0: Verify Server Connectivity

```yaml
# ~/.hermes/config.yaml
mcp_lumen:
  enabled: true

mcp_servers:
  lumen_thinking:
    command: "python"
    args: ["path/to/lumen-protocol/implementations/mcp-servers/thinking/server.py"]
    transport: lumen
    lumen_force_json_rpc: true
    enabled: true

  lumen_filesystem:
    command: "python"
    args: ["path/to/lumen-protocol/implementations/mcp-servers/filesystem/server.py"]
    transport: lumen
    enabled: true

  lumen_web:
    command: "python"
    args: ["path/to/lumen-protocol/implementations/mcp-servers/web/server.py"]
    transport: lumen
    lumen_force_json_rpc: true
    enabled: true
```

After `/reset`, all 33 tools appear as `mcp_lumen_thinking_*`, `mcp_lumen_filesystem_*`, `mcp_lumen_web_*`.

---

## Phase 1: Auto-Context Preservation Hook

Long conversations (>30 turns) silently lose critical constraints. `context_preserve`
anchors them against decay.

### Hermes Plugin: `lumen-context-anchor`

Create `~/AppData/Local/hermes/plugins/lumen-context-anchor/__init__.py`:

```python
"""Auto-anchor critical context to Lumen Thinking on long conversations."""
from hermes.plugin_api import PluginContext

TURN_THRESHOLD = 30
_anchored = set()

async def on_turn_end(ctx: PluginContext, turn_number: int) -> None:
    """After turn 30, auto-preserve user constraints, key decisions, errors."""
    label = f"auto_turn_{turn_number}"
    if label in _anchored:
        return

    # Collect recent user constraints and assistant decisions
    msgs = ctx.get_recent_messages(n=5)
    content = "\n".join(f"[{m['role']}] {m['content'][:300]}" for m in msgs)

    ctx.call_mcp_tool("lumen_thinking", "context_preserve", {
        "label": label,
        "content": content,
        "ttl_seconds": 3600
    })
    _anchored.add(label)


def register(ctx: PluginContext) -> None:
    ctx.register_hook("on_turn_end", on_turn_end)
```

Hermes config:
```yaml
plugins:
  lumen-context-anchor:
    enabled: true
```

---

## Phase 2: Thought-to-Plan Bridge

`thought_to_plan` converts reasoning chains to actionable plans. Bridge it to
Hermes's `.hermes/plans/` directory.

### Hermes Plugin: `lumen-plan-bridge`

```python
"""Bridge Lumen thought_to_plan → .hermes/plans/ directory."""
from hermes.plugin_api import PluginContext
import json, pathlib, datetime

def register(ctx: PluginContext) -> None:
    plans_dir = pathlib.Path(ctx.hermes_home) / "plans"

    def lumen_to_plan_handler(args: dict) -> dict:
        """Wraps thought_to_plan and auto-saves to .hermes/plans/."""
        result = ctx.call_mcp_tool("lumen_thinking", "thought_to_plan", {
            "chainId": args["chainId"],
            "format": "markdown"
        })

        chain_id = args["chainId"]
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        plan_path = plans_dir / f"lumen-plan-{chain_id}-{ts}.md"
        plans_dir.mkdir(parents=True, exist_ok=True)

        plan_path.write_text(result["plan"])

        return {
            "content": [{"type": "text", "text":
                f"Plan saved to {plan_path}\n\n{result['plan']}"}]
        }

    # Register as override: same name, transparent replacement
    ctx.register_tool(
        name="mcp_lumen_thinking_thought_to_plan",
        toolset="lumen-native",
        schema=THOUGHT_TO_PLAN_SCHEMA,  # identical schema
        handler=lumen_to_plan_handler,
        override=True
    )
```

---

## Phase 3: Cognitive Tools as Subagent Capabilities

Subagents (via `delegate_task`) can use Lumen Thinking tools for isolated reasoning:

```python
# Parent agent delegates a debugging task
delegate_task(
    goal="Debug the API timeout root cause",
    context="""
    Symptoms: GET /api/users returns 504 after 30s. EU region only. Peak hours.
    Stack: Nginx → Node 20. DB connection pool exhausted.
    Available MCP tools: mcp_lumen_thinking_sequential_thinking,
      mcp_lumen_thinking_thought_contradiction,
      mcp_lumen_thinking_context_preserve,
      mcp_lumen_filesystem_read_file,
      mcp_lumen_filesystem_search_files
    Use the scientific debugging workflow: preserve context → hypotheses →
    contradiction check → evaluate → capture root cause pattern.
    Return your reasoning chain ID and the identified root cause.
    """,
    toolsets=["terminal", "file", "web"]
)
```

The subagent inherits MCP tools automatically when `delegation.inherit_mcp_toolsets: true`.

---

## Phase 4: Disable Built-in Equivalents (Optional)

When Lumen tools are strictly superior, disable Hermes built-ins to reduce tool schema
size and avoid confusion:

```yaml
tools:
  disabled_toolsets: ["file"]  # Use lumen_filesystem instead

# More granular: disable specific tools
mcp_servers:
  lumen_thinking:
    disabled_tools: []  # keep all thinking tools
  lumen_filesystem:
    disabled_tools: ["read_file", "write_file", "patch", "search_files"]
    # ^ keep the EXCLUSIVE filesystem tools (list_directory, read_files, etc.)
```

---

## Cognitive Infrastructure Dashboard

After Phase 3, your Hermes cognitive stack:

```
┌─────────────────────────────────────────────┐
│              HERMES AGENT                    │
│  ┌──────────────┐  ┌──────────────────────┐ │
│  │ Built-in Core │  │ LUMEN Cognitive Layer│ │
│  │ • terminal    │  │ • Reasoning Engine   │ │
│  │ • browser     │  │ • Assumption Tracker │ │
│  │ • web_search  │  │ • Mental Model       │ │
│  │ • file ops    │  │ • Context Anchor     │ │
│  └──────────────┘  │ • Work Tracker       │ │
│                     │ • Context Estimator  │ │
│  ┌──────────────────────────────────────┐   │
│  │ PLUGINS: auto-context + plan-bridge  │   │
│  └──────────────────────────────────────┘   │
│  ┌──────────────────────────────────────┐   │
│  │ FILESYSTEM: 9 LUMEN MCP tools        │   │
│  └──────────────────────────────────────┘   │
│  ┌──────────────────────────────────────┐   │
│  │ WEB: 2 LUMEN MCP tools               │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

---

## Pitfalls

- **Prompt cache invalidation**: Adding MCP servers adds tools to the schema. First turn
  after `/reset` is more expensive. Subsequent turns reuse cached prefix.
- **Tool name collisions**: MCP tools get `mcp_<server>_<tool>` prefix by design.
  No collision with built-ins. Plugins with `override=True` are the exception.
- **Subagent context**: Subagents don't inherit the parent's reasoning state.
  Pass `chainId` explicitly if continuing a parent's chain.
- **Plugin lifecycle**: Plugins are loaded at Hermes start. After creating a plugin,
  restart Hermes or `/reload-plugins`.
- **Windows Python path**: Always use full path to hermes venv python.
  ```yaml
  command: "C:/Users/<user>/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe"
  ```
