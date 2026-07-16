# DDP API — Routines + Data Access for LLMs

This document describes how an LLM (or any agent) can use the DDP API to:
- Browse imported MSM routines
- Read clinical/production data from the PDB
- Generate M code that follows real patterns

## Endpoints

### Routines

```
GET /ddp/routine              → List all available routines (max 2000)
GET /ddp/routine?name=AB01L   → Get full source code of a routine
```

**Example — LLM requests a pattern:**
```bash
curl http://localhost:8081/ddp/routine?name=AB01L
```
```json
{
  "success": true,
  "name": "AB01L",
  "code": "AB01L ;-- Llista de Ep ABS D'un Exp --\n S EXP=$P(PARAM,\"#\",1)\n ..."
}
```

**Response fields:**
| Field | Type | Description |
|---|---|---|
| `success` | bool | Whether the query succeeded |
| `name` | string | Routine name (uppercase) |
| `code` | string | Full M source code (newline-separated lines) |

### Data (Namespaces)

```
GET /ddp/pull?ns=X            → Pull all entries from namespace X
GET /ddp/pull?ns=X&prefix=A   → Pull entries under prefix A (sub-tree)
GET /ddp/pull?ns=_all_        → Pull all namespaces (may be slow)
```

**Example — LLM explores clinical data structure:**
```bash
curl http://localhost:8081/ddp/pull?ns=clinica
# Returns top-level folders: asi, clinico, dmf, gowin

curl http://localhost:8081/ddp/pull?ns=clinica&prefix=asi
# Returns all entries under clinica/asi (5.3K entries)
```

**Example — LLM checks available data namespaces:**
```bash
curl http://localhost:8081/ddp/pull?ns=HEARTBEAT
```

### Write Data

```
POST /ddp/push
Content-Type: application/json

{"ns": "MY_NS", "entries": [{"subs": ["key"], "value": "data"}]}
```

## How an LLM can use this

### 1. Study real patterns

An LLM can fetch production MUMPS routines and learn their patterns:

```python
import requests
r = requests.get("http://localhost:8081/ddp/routine?name=AB01L")
code = r.json()["code"]
# Analyze $ORDER loop, $P parsing, SET with indexes
```

### 2. Generate M code following those patterns

```python
# After analyzing AB01L (a list builder), the LLM generates:
generated = """
MYLIST ; List builder for ^MYDATA
 N k,res S res=""
 S k=$O(^MYDATA(k)) G:k="" MLIST
ML1 S res=res_$G(^MYDATA(k))_"#"
 S k=$O(^MYDATA(k)) G:k="" ML1
ML1 Q res
"""
```

### 3. Generate and test on WASM

The LLM generates M code, compiles it with `m_compile()`, and tests it with `m_execute_ddp()` in the WASM console.

### 4. Push changes back

```bash
curl -X POST http://localhost:8081/ddp/push \
  -H "Content-Type: application/json" \
  -d '{"ns":"MYDATA","entries":[{"subs":["k1"],"value":"hello"}]}'
```

## Available data (~540K total PDB entries)

| Namespace | Entries | Content |
|---|---|---|
| clinica/asi | 5,375 | Primary Care visits (MSM ASI volume) |
| clinica/dmf | — | Dietetics/Medication (MSM DMF volume) |
| clinica/gowin | — | GOWIN volume (MSM GOWIN) |
| HEARTBEAT | 2 | Agent health status |
| STATE | 744 | VM state entries |
| ROUTINE | ~37K | MUMPS routines (MSM system + GWSK + RUTS) |

## Notes

- PDB is case-sensitive for namespace names (use exact case from the source)
- Binary subscripts (from MSM) contain 0x00 bytes — use `?prefix=` to navigate
- `_all_` scans every namespace (168+ currently) and may take >30s
- Routines are stored as ROUTINE(name, line_number) = "source line"
