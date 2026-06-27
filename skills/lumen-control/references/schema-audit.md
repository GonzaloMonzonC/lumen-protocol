# Schema Audit Methodology

## When creating an MCP server that mirrors Hermes built-in tools

The LLM's cached system prompt assumes specific tool schemas. If your MCP server
uses different schemas, the LLM generates calls with missing parameters, causing
errors and degraded UX.

### Audit checklist

1. **Parameter names**: must match EXACTLY (case-sensitive)
2. **Parameter types**: string, integer, boolean, array, enum
3. **Required fields**: must be identical
4. **Default values**: if Hermes has `default: 500`, you must too
5. **Description text**: should be close, but not critical

### Found in this session

| Tool | Hermes property | Our server (before fix) |
|------|----------------|------------------------|
| `patch` | `mode: {type:string, enum:[replace,patch], default:replace}` | MISSING |
| `patch` | `cross_profile: {type:boolean, default:false}` | MISSING |
| `search_files` | `output_mode: {type:string, enum:[content,files_only,count]}` | MISSING |
| `search_files` | `context: {type:integer, default:0}` | MISSING |
| `search_files` | `offset: {type:integer, default:0}` | MISSING |

These were added. The LLM may not use these advanced properties often, but when
it does, missing them causes silent failures or incorrect behavior.

### How to audit

```python
import re, ast

# Extract Hermes schema
hermes_schema = ast.literal_eval(hermes_source_code)

# Compare with your MCP tool inputSchema
for prop in hermes_schema['parameters']['properties']:
    if prop not in your_input_schema['properties']:
        print(f"MISSING: {prop}")
    elif hermes_schema['parameters']['properties'][prop] != your_input_schema['properties'][prop]:
        print(f"MISMATCH: {prop}")
```

### Result size limits

Hermes tools have `max_result_size_chars=100_000`. Your MCP server should respect
the same limit to avoid flooding the LLM context. Add truncation with a clear
message like `... (truncated at N/M, result too large)`.
