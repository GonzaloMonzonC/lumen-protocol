import re

p = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking\server.py'
with open(p) as f:
    content = f.read()

# ── 1. Constants ──
content = content.replace(
    '_PDB_SNAPSHOT_INTERVAL = 5  # PDB snapshot every N saves (0=disable)',
    '_JSON_SNAPSHOT_INTERVAL = 50  # JSON snapshot every N saves (0=disable)'
)

# ── 2. Replace _save_state() ──
old_save_start = 'def _save_state() -> None:\n    """Persist all state to disk atomically."""'
idx_start = content.find(old_save_start)
idx_end = content.find('\ndef _new_chain', idx_start)

if idx_start > 0 and idx_end > idx_start:
    new_save_body = '''def _save_state() -> None:
    """Persist all state to PDB (primary) + optionally JSON snapshot."""
    global _save_counter, _json_snap_counter
    _save_counter = 0
    _json_snap_counter += 1
    try:
        # PDB: write all current state as individual records
        _pdb_save_all()
        # JSON snapshot (periodic backup)
        if _JSON_SNAPSHOT_INTERVAL > 0 and _json_snap_counter >= _JSON_SNAPSHOT_INTERVAL:
            _json_snap_counter = 0
            threading.Thread(target=_json_snapshot, daemon=True).start()
    except Exception as e:
        _safe_print(f"[lumen-thinking] Failed to save state: {e}")

_json_snap_counter = 0
'''
    content = content[:idx_start] + new_save_body + content[idx_end:]
    print('✓ _save_state replaced')
else:
    print(f'✗ _save_state not found: {idx_start}-{idx_end}')
    # Try alternate start
    alt = 'def _save_state():'
    idx_start = content.find(alt)
    print(f'  Alt search: {idx_start}')

# ── 3. Replace _load_state() ──  
old_load_start = 'def _load_state() -> bool:\n    """Restore state from disk. Returns True if state was loaded."""'
idx_start = content.find(old_load_start)
if idx_start < 0:
    old_load_start = 'def _load_state() -> bool:\n    """Restore state from disk. Returns True if state was loaded."""'
    old_load_start = 'def _load_state() -> bool:\n    """Restore state from PDB first, then JSON fallback."""'
    idx_start = content.find(old_load_start)

# Find end: next function definition after _load_state
if idx_start > 0:
    idx_end = content.find('\ndef _auto_save', idx_start)
    if idx_end < 0:
        # Try to find by searching for '_get_session'
        idx_end = content.find('\ndef _get_session', idx_start)
    
    if idx_end > idx_start:
        new_load = '''def _load_state() -> bool:
    """Restore state from PDB first, then JSON fallback."""
    global _sessions, _next_session_num, _preserved, _loaded_from_disk

    # Try PDB first (primary storage)
    if _pdb_load_all():
        _loaded_from_disk = True
        _safe_print("[lumen-thinking] State restored from PDB")
        return True

    # Try JSON as fallback (legacy / backup)
    if not _STATE_FILE.exists():
        _safe_print("[lumen-thinking] No saved state found — starting fresh.")
        return False
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        _sessions = {sid: Session.from_dict(sd) for sid, sd in state.get("sessions", {}).items()}
        _next_session_num = state.get("next_session_num", 1)
        _preserved = state.get("preserved", [])
        if "timeline" in state:
            _call_timeline[:] = state["timeline"]
        global _agent_messages, _global_patterns
        global _niches, _tasks, _next_niche_id, _next_task_id
        global _web_snapshots, _last_state_mtime
        global _qa_pairs
        _agent_messages = state.get("agent_messages", [])
        _niches = state.get("niches", {})
        _tasks = state.get("tasks", {})
        _next_niche_id = state.get("next_niche_id", 1)
        _next_task_id = state.get("next_task_id", 1)
        _global_patterns = state.get("global_patterns", [])
        _web_snapshots = state.get("web_snapshots", {})
        _qa_pairs = state.get("qa_pairs", {})
        _loaded_from_disk = True
        global _file_claims
        _file_claims = state.get("file_claims", {})
        load_objective_state(state)
        _last_state_mtime = _STATE_FILE.stat().st_mtime if _STATE_FILE.exists() else 0.0
        total_chains = sum(len(s.chains) for s in _sessions.values())
        total_patterns = sum(len(s.patterns) for s in _sessions.values())
        saved_at = state.get("saved_at", "unknown")
        max_id = 0
        for s in _sessions.values():
            for a in s.assumptions:
                if a.get("id", 0) > max_id:
                    max_id = a["id"]
        global _next_assumption_id
        _next_assumption_id = max_id + 1
        _safe_print(f"[lumen-thinking] State restored from JSON: {total_chains} chains, {total_patterns} patterns, "
                     f"{len(_preserved)} preserved items across {len(_sessions)} sessions "
                     f"(saved {saved_at})")
        return True
    except Exception as e:
        _safe_print(f"[lumen-thinking] Failed to load JSON state: {e} — starting fresh.")
        return False

'''
        content = content[:idx_start] + new_load + content[idx_end:]
        print('✓ _load_state replaced')
    else:
        print(f'✗ _load_state end not found: {idx_start}-{idx_end}')
else:
    print(f'✗ _load_state not found: {idx_start}')

# ── 4. Add _pdb_save_all, _pdb_load_all, _json_snapshot functions ──
# Insert them before _load_state (or after _save_state and _json_snap_counter)
new_functions = '''

def _pdb_save_all() -> None:
    """Write ALL state to PDB as individual records."""
    try:
        conn = sqlite3.connect(str(_PDB_PATH))
        conn.execute("DELETE FROM _globals WHERE ns='STATE'")
        pairs = []

        for sid, sess in _sessions.items():
            pairs.append(("STATE", f"session:{sid}:info".encode(), json.dumps(sess.to_dict()).encode()))
            for cid, chain in sess.chains.items():
                pairs.append(("STATE", f"session:{sid}:chain:{cid}".encode(), json.dumps(chain).encode()))
            for a in sess.assumptions:
                pairs.append(("STATE", f"session:{sid}:assumption:{a['id']}".encode(), json.dumps(a).encode()))
            for name, entity in sess.model.items():
                pairs.append(("STATE", f"session:{sid}:model:{name}".encode(), json.dumps(entity).encode()))
            for w in sess.works:
                pairs.append(("STATE", f"session:{sid}:work:{w['id']}".encode(), json.dumps(w).encode()))
            for pat in sess.patterns:
                pairs.append(("STATE", f"session:{sid}:pattern:{pat.get('name','?')}".encode(), json.dumps(pat).encode()))
            for d in sess.decisions:
                pairs.append(("STATE", f"session:{sid}:decision:{d['id']}".encode(), json.dumps(d).encode()))
            for title, page in sess.wiki.items():
                pairs.append(("STATE", f"session:{sid}:wiki:{title}".encode(), json.dumps(page).encode()))

        for i, p in enumerate(_preserved):
            pairs.append(("STATE", f"global:preserved:{i}".encode(), json.dumps(p).encode()))
        for i, t in enumerate(_call_timeline):
            pairs.append(("STATE", f"global:timeline:{i}".encode(), json.dumps(t).encode()))
        for i, ft in enumerate(_file_touches):
            pairs.append(("STATE", f"global:file_touch:{i}".encode(), json.dumps(ft).encode()))
        for fp, claim in _file_claims.items():
            pairs.append(("STATE", f"global:file_claim:{fp}".encode(), json.dumps(claim).encode()))
        for i, m in enumerate(_agent_messages):
            pairs.append(("STATE", f"global:agent_msg:{i}".encode(), json.dumps(m).encode()))
        for i, p in enumerate(_global_patterns):
            pairs.append(("STATE", f"global:pattern:{i}".encode(), json.dumps(p).encode()))
        for sid, snap in _web_snapshots.items():
            pairs.append(("STATE", f"global:web_snapshot:{sid}".encode(), json.dumps(snap).encode()))
        for qid, qa in _qa_pairs.items():
            pairs.append(("STATE", f"global:qa:{qid}".encode(), json.dumps(qa).encode()))
        for nid, niche in _niches.items():
            pairs.append(("STATE", f"global:niche:{nid}".encode(), json.dumps(niche).encode()))
        for tid, task in _tasks.items():
            pairs.append(("STATE", f"global:task:{tid}".encode(), json.dumps(task).encode()))
        try:
            from objective_loop import _objectives, _next_objective_id
            for gid, obj in _objectives.items():
                pairs.append(("STATE", f"global:objective:{gid}".encode(), json.dumps(obj).encode()))
            pairs.append(("STATE", "global:objective_meta".encode(), json.dumps({"next_id": _next_objective_id}).encode()))
        except ImportError:
            pass

        meta = {"next_session_num": _next_session_num, "next_niche_id": _next_niche_id, "next_task_id": _next_task_id, "saved_at": time.time()}
        pairs.append(("STATE", "global:meta".encode(), json.dumps(meta).encode()))
        conn.executemany("INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)", pairs)
        conn.commit()
        conn.close()
    except Exception as e:
        _safe_print(f"[lumen-thinking] PDB save FAILED: {e}")


def _pdb_load_all() -> bool:
    """Load ALL state from PDB. Returns True if state was loaded."""
    global _sessions, _next_session_num, _preserved, _call_timeline
    global _file_touches, _file_claims, _agent_messages, _global_patterns
    global _web_snapshots, _qa_pairs, _niches, _tasks, _next_niche_id, _next_task_id
    try:
        if not _PDB_PATH.exists():
            return False
        conn = sqlite3.connect(str(_PDB_PATH))
        rows = conn.execute("SELECT subkey, value FROM _globals WHERE ns='STATE'").fetchall()
        conn.close()
        if not rows:
            return False

        records = {}
        for sk, val in rows:
            sk = sk.decode() if isinstance(sk, bytes) else sk
            val = json.loads(val.decode() if isinstance(val, bytes) else val)
            records[sk] = val

        sessions_data = {}
        globals_data = {}
        for sk, val in records.items():
            if sk.startswith("session:"):
                parts = sk.split(":", 3)
                if len(parts) >= 3:
                    sid = parts[1]
                    if sid not in sessions_data:
                        sessions_data[sid] = {"chains": {}, "assumptions": [], "decisions": [],
                                              "works": [], "patterns": [], "model": {}, "wiki": {}, "bridges": []}
                    sub = parts[2]
                    if sub == "info":
                        sessions_data[sid]["info"] = val
                    elif sub == "chain":
                        sessions_data[sid]["chains"][parts[3]] = val
                    elif sub == "assumption":
                        sessions_data[sid]["assumptions"].append(val)
                    elif sub == "decision":
                        sessions_data[sid]["decisions"].append(val)
                    elif sub == "work":
                        sessions_data[sid]["works"].append(val)
                    elif sub == "pattern":
                        sessions_data[sid]["patterns"].append(val)
                    elif sub == "model":
                        sessions_data[sid]["model"][parts[3]] = val
                    elif sub == "wiki":
                        sessions_data[sid]["wiki"][parts[3]] = val
            elif sk.startswith("global:"):
                globals_data[sk] = val

        for sid, data in sessions_data.items():
            info = data.get("info", {})
            s = Session.from_dict(info)
            s.chains = data["chains"]
            s.assumptions = data["assumptions"]
            s.decisions = data["decisions"]
            s.works = data["works"]
            s.patterns = data["patterns"]
            s.model = data["model"]
            s.wiki = data["wiki"]
            s.bridges = data["bridges"]
            _sessions[sid] = s

        _preserved = [v for k, v in globals_data.items() if k.startswith("global:preserved:")]
        _call_timeline = [v for k, v in sorted(globals_data.items()) if k.startswith("global:timeline:")]
        _file_touches = [v for k, v in sorted(globals_data.items()) if k.startswith("global:file_touch:")]
        _file_claims = {k.split(":", 2)[2]: v for k, v in globals_data.items() if k.startswith("global:file_claim:")}
        _agent_messages = [v for k, v in sorted(globals_data.items()) if k.startswith("global:agent_msg:")]
        _global_patterns = [v for k, v in sorted(globals_data.items()) if k.startswith("global:pattern:")]
        _web_snapshots = {k.split(":", 2)[2]: v for k, v in globals_data.items() if k.startswith("global:web_snapshot:")}
        _qa_pairs = {k.split(":", 2)[2]: v for k, v in globals_data.items() if k.startswith("global:qa:")}
        _niches = {k.split(":", 2)[2]: v for k, v in globals_data.items() if k.startswith("global:niche:")}
        _tasks = {k.split(":", 2)[2]: v for k, v in globals_data.items() if k.startswith("global:task:")}

        objectives = {}
        objective_meta = {}
        for k, v in globals_data.items():
            if k.startswith("global:objective:") and k != "global:objective_meta":
                gid = k.split(":", 2)[2]; objectives[gid] = v
            elif k == "global:objective_meta":
                objective_meta = v
        if objectives or objective_meta:
            try:
                from objective_loop import load_objective_state
                load_objective_state({"objectives": objectives, "next_objective_id": objective_meta.get("next_id", 1)})
            except ImportError:
                pass

        meta = globals_data.get("global:meta", {})
        _next_session_num = meta.get("next_session_num", 1)
        _next_niche_id = meta.get("next_niche_id", 1)
        _next_task_id = meta.get("next_task_id", 1)

        _safe_print(f"[lumen-thinking] PDB restored: {len(_sessions)} sessions, "
                     f"{sum(len(s.chains) for s in _sessions.values())} chains, "
                     f"{len(_niches)} niches, {len(_tasks)} tasks, {len(objectives)} objectives")
        return True
    except Exception as e:
        _safe_print(f"[lumen-thinking] PDB load FAILED: {e}")
        return False


def _json_snapshot() -> None:
    """Periodic JSON snapshot for backup/portability. Runs every _JSON_SNAPSHOT_INTERVAL saves."""
    try:
        total_calls = sum(s.tool_calls for s in _sessions.values())
        now = time.time()
        hour_key = int(now // 3600)
        if _call_timeline and isinstance(_call_timeline[-1], dict) and _call_timeline[-1].get("hour") == hour_key:
            _call_timeline[-1]["calls"] = total_calls
            _call_timeline[-1]["ts"] = now
        else:
            _call_timeline.append({"hour": hour_key, "ts": now, "calls": total_calls,
                "delta": total_calls - (_call_timeline[-1].get("calls", 0) if _call_timeline else 0)})
        cutoff_hour = hour_key - 48
        _call_timeline[:] = [b for b in _call_timeline if b["hour"] > cutoff_hour]
        if len(_call_timeline) > 200:
            _call_timeline[:] = _call_timeline[-200:]

        state = {
            "sessions": {sid: s.to_dict() for sid, s in _sessions.items()},
            "next_session_num": _next_session_num,
            "preserved": _preserved,
            "timeline": _call_timeline,
            "presence": {sid: {"pid": os.getpid(), "last_seen": time.time(), "tool_calls": s.tool_calls, "model": s.model_name or "unknown"} for sid, s in _sessions.items()},
            "file_touches": _file_touches[-200:],
            "file_claims": _file_claims,
            "agent_messages": _agent_messages[-100:],
            "global_patterns": _global_patterns[-300:],
            "web_snapshots": {k: v for k, v in _web_snapshots.items()},
            "qa_pairs": {k: v for k, v in _qa_pairs.items()},
            "niches": {nid: n for nid, n in _niches.items()},
            "tasks": {tid: t for tid, t in _tasks.items()},
            "next_niche_id": _next_niche_id,
            "next_task_id": _next_task_id,
            "saved_at": time.time(),
            **get_objective_state(),
        }
        tmp = str(_STATE_FILE) + ".tmp"
        if os.path.exists(tmp):
            try: os.remove(tmp)
            except OSError: pass
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)
        for attempt in range(3):
            try:
                os.replace(tmp, str(_STATE_FILE))
                break
            except (OSError, PermissionError):
                if attempt < 2:
                    time.sleep(0.05)
                else:
                    with open(str(_STATE_FILE), "w", encoding="utf-8") as f:
                        json.dump(state, f, ensure_ascii=False, indent=2, default=str)
                    try: os.remove(tmp)
                    except OSError: pass
        _safe_print(f"[lumen-thinking] JSON snapshot saved ({len(state)} keys)")
    except Exception as e:
        _safe_print(f"[lumen-thinking] JSON snapshot FAILED: {e}")

'''

# Insert new functions BEFORE _load_state
load_start = content.find('\ndef _load_state')
if load_start > 0:
    content = content[:load_start] + new_functions + content[load_start:]
    print('✓ New functions inserted before _load_state')
else:
    print('✗ Could not find _load_state insertion point')

# ── 5. Write and verify ──
with open(p, 'w') as f:
    f.write(content)

import py_compile
try:
    py_compile.compile(p, doraise=True)
    print('✓ Syntax OK')
except py_compile.PyCompileError as e:
    print(f'✗ Syntax error: {e}')
