# PDB Persistence for Agent Loop Objectives

**Date**: 2026-06-22  
**Status**: VERIFIED ✓  
**Server file**: `implementations/mcp-servers/thinking/server.py`

## Problem

The Agent Loop objectives (`_objectives` dict in `objective_loop.py`) were only persisted through JSON state (`_save_state()` / `_load_state()`). The PDB snapshot backup (`_pdb_snapshot()` / `_pdb_load_snapshot()`) did NOT include objectives. If `.thinking_state.json` was lost (taskkill, crash), objectives would vanish.

## The 3 Sub-Layer Fix

All three were missing. Each had to be wired independently.

### Layer 1: `_pdb_snapshot()` — Save objectives to SQLite

**File**: `server.py`, around line 254

**Before**:
```python
        for name, entity in sess.model.items():
                v = json.dumps(entity)
                pairs.append(("SNAPSHOT", f"m:{name}".encode(), v.encode()))
        conn.executemany("INSERT OR REPLACE INTO _globals ...")
```

**After**:
```python
        for name, entity in sess.model.items():
                v = json.dumps(entity)
                pairs.append(("SNAPSHOT", f"m:{name}".encode(), v.encode()))
        # Save objectives at module level (not per-session)
        from objective_loop import _objectives, _next_objective_id
        pairs.append(("SNAPSHOT", "objective:state".encode(),
                      json.dumps({"objectives": _objectives,
                                  "next_objective_id": _next_objective_id}).encode()))
        conn.executemany("INSERT OR REPLACE INTO _globals ...")
```

**Key detail**: Import inside the function to avoid circular import at module level. Single subkey `"objective:state"` holds the entire dict — atomic save, atomic load.

### Layer 2: `_pdb_load_snapshot()` — Restore objectives from SQLite

**File**: `server.py`, around line 271

Add init vars after the unpacking line:
```python
        chains, decisions, assumptions, works, patterns, wiki, model = {}, [], [], [], [], {}, {}
        objectives = {}
        next_obj_id = 1
```

Add objective parsing inside the subkey loop:
```python
            elif sk == "objective:state":
                objectives = v.get("objectives", {})
                next_obj_id = v.get("next_objective_id", 1)
```

Add objectives to the return dict:
```python
        return {"chains": chains, ..., "model": model,
                "objectives": objectives, "next_objective_id": next_obj_id}
```

### Layer 3: `_load_state()` PDB fallback — Call `load_objective_state()`

**File**: `server.py`, around line 317

**Before**:
```python
            if sess.works:
                global _next_work_id
                _next_work_id = max(w["id"] for w in sess.works) + 1
            return True
```

**After**:
```python
            if sess.works:
                global _next_work_id
                _next_work_id = max(w["id"] for w in sess.works) + 1
            # Restore objectives from PDB snapshot
            load_objective_state({"objectives": pdb.get("objectives", {}),
                                  "next_objective_id": pdb.get("next_objective_id", 1)})
            return True
```

## Verification Checklist

- [x] `_save_state()` includes `**get_objective_state()` — was already working
- [x] `_load_state()` calls `load_objective_state(state)` — was already working
- [x] `_pdb_snapshot()` saves `"objective:state"` subkey — FIXED
- [x] `_pdb_load_snapshot()` reads `"objective:state"` and returns it — FIXED
- [x] PDB fallback path in `_load_state()` calls `load_objective_state()` — FIXED
- [x] Python syntax valid after all patches (`py_compile.compile`)
- [x] `server_shm.py` picks up fixes automatically (imports from `server.py`)

## General Pattern

Every new module added to the thinking server needs 5 wiring points:

| Point | Where | What |
|-------|-------|------|
| State getter | `objective_loop.py` | `get_objective_state()` returns dict |
| State loader | `objective_loop.py` | `load_objective_state(dict)` restores globals |
| JSON save | `server.py::_save_state` | `**get_objective_state()` merge |
| JSON load | `server.py::_load_state` | `load_objective_state(state)` call |
| PDB save | `server.py::_pdb_snapshot` | Write subkey to SQLite |
| PDB load | `server.py::_pdb_load_snapshot` | Parse subkey, return in dict |
| PDB fallback | `server.py::_load_state` | Call loader with PDB result |
