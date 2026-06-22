# PDB-First Persistence Architecture

## Current Architecture (JSON-first)

```
Tool call → _get_session() → _auto_save()
  → cada 10 calls: _save_state()
    → Escribe .thinking_state.json COMPLETO (~100KB)
    → threads every 5 saves: _pdb_snapshot()
      → Escribe cada registro individual en PDB (SNAPSHOT ns)
```

**Problemas:**
- Reescribe 100KB+ cada 10 tool calls → I/O innecesario
- Si el proceso muere durante `json.dump()` → archivo corrupto
- El reintento atómico con `.tmp` + `os.replace()` es frágil en Windows (file locking)

## New Architecture (PDB-first)

```
Tool call → _get_session() → _auto_save()
  → cada 10 calls: _pdb_save_dirty()
    → Solo escribe registros INDIVIDUALES que cambiaron
    → UPDATE/INSERT en _globals table por subkey
  → cada 50 calls: _json_snapshot()
    → Snapshot JSON completo (backup, no primario)
```

### PDB Namespace Layout

All data stored in `_globals(ns='STATE', subkey, value)`:

| Subkey prefix | Data | Granularity |
|--------------|------|-------------|
| `session:{sid}:info` | Session metadata | 1 record/session |
| `session:{sid}:chain:{cid}` | Chain thoughts + metadata | 1 record/chain |
| `session:{sid}:assumption:{id}` | Single assumption | 1 record/assumption |
| `session:{sid}:model:{name}` | Model entity | 1 record/entity |
| `session:{sid}:work:{id}` | Work item | 1 record/work |
| `session:{sid}:pattern:{name}` | Pattern | 1 record/pattern |
| `session:{sid}:decision:{id}` | Decision | 1 record/decision |
| `session:{sid}:bridge:{n}` | Bridge result | 1 record/bridge |
| `session:{sid}:wiki:{title}` | Wiki page | 1 record/wiki |
| `global:niche:{nid}` | Kanban niche | 1 record/niche |
| `global:task:{tid}` | Kanban task | 1 record/task |
| `global:objective:{gid}` | Agent Loop objective | 1 record/objective |
| `global:preserved:{label}` | Preserved context | 1 record/item |
| `global:timeline:{n}` | Timeline entry | 1 record/entry |
| `global:file_touches:{n}` | File touch | 1 record/touch |
| `global:file_claims:{path}` | File claim | 1 record/claim |
| `global:agent_messages:{n}` | Agent message | 1 record/msg |
| `global:patterns:{name}` | Global pattern | 1 record/pattern |
| `global:web_snapshots:{id}` | Web snapshot | 1 record/snapshot |
| `global:qa:{id}` | Q&A pair | 1 record/qa |
| `global:meta` | Counters (next_ids, etc.) | 1 record |

### Save Flow

1. `_pdb_save_all()` called by `_save_state()`:
   - DELETE FROM _globals WHERE ns='STATE'
   - INSERT all current records individually
   - Single transaction → ACID

2. `_pdb_load_all()` called by `_load_state()`:
   - SELECT * FROM _globals WHERE ns='STATE'
   - Reconstruct sessions dict + globals

3. JSON snapshot (`_json_snapshot()`):
   - Same as current `_save_state()` but only every 50 calls
   - For backup/portability only

### Migration

- `_pdb_load_all()` reads STATE namespace → if empty, falls back to JSON
- On first load from JSON, `_pdb_save_all()` migrates to PDB
- After that, PDB is primary
