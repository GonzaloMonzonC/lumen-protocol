"""
Clean PDB-first migration — surgical patches to server.py
"""
import re

p = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking\server.py'
with open(p) as f:
    content = f.read()

# 1) Constants
content = content.replace(
    '_PDB_SNAPSHOT_INTERVAL = 5  # PDB snapshot every N saves (0=disable)',
    '_JSON_SNAPSHOT_INTERVAL = 50  # JSON snapshot every N saves (0=disable)'
)

# 2) _pdb_snap_counter → _json_snap_counter
content = content.replace('_pdb_snap_counter', '_json_snap_counter')

# 3) _save_state: replace body to call _pdb_save_all + periodic _json_snapshot
old_save = '''def _save_state() -> None:
    """Persist all state to disk atomically."""
    global _save_counter, _json_snap_counter
    _save_counter = 0
    _json_snap_counter += 1
    if _JSON_SNAPSHOT_INTERVAL > 0 and _json_snap_counter >= _JSON_SNAPSHOT_INTERVAL:
        _json_snap_counter = 0
        threading.Thread(target=_pdb_snapshot, daemon=True).start()

    try:
        # Record timeline snapshot with hourly bucketing
        total_calls = sum(s.tool_calls for s in _sessions.values())
        now = time.time()
        hour_key = int(now // 3600)  # bucket by hour

        # Find or create this hour's bucket
        if _call_timeline and _call_timeline and isinstance(_call_timeline[-1], dict) and _call_timeline[-1].get("hour") == hour_key:
            _call_timeline[-1]["calls"] = total_calls
            _call_timeline[-1]["ts"] = now
        else:
            _call_timeline.append({"hour": hour_key, "ts": now, "calls": total_calls, "delta": total_calls - (_call_timeline[-1].get("calls", 0) if _call_timeline else 0)})

        # Keep last 48h (48 buckets)
        cutoff_hour = hour_key - 48
        _call_timeline[:] = [b for b in _call_timeline if b["hour"] > cutoff_hour]
        # Keep last 200 snapshots (~30min at 10s intervals)
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
            "agent_messages": _agent_messages[-100:],  # last 100 messages
            "global_patterns": _global_patterns[-300:],
            "web_snapshots": {k:v for k,v in _web_snapshots.items()},
            "qa_pairs": {k:v for k,v in _qa_pairs.items()},
            "niches": {nid: n for nid, n in _niches.items()},
            "tasks": {tid: t for tid, t in _tasks.items()},
            "next_niche_id": _next_niche_id,
            "next_task_id": _next_task_id,
            "saved_at": time.time(),
            **get_objective_state(),
        }
        tmp = str(_STATE_FILE) + ".tmp"
        # Clean up stale tmp file if it exists
        if os.path.exists(tmp):
            try: os.remove(tmp)
            except OSError: pass
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)
        # Retry atomic replace on Windows file locking (dashboard may have file open)
        for attempt in range(5):
            try:
                os.replace(tmp, str(_STATE_FILE))
                break
            except (OSError, PermissionError) as e:
                if attempt < 4:
                    time.sleep(0.01 * (2 ** attempt))  # exponential backoff
                else:
                    # Last resort: write directly
                    try:
                        with open(str(_STATE_FILE), "w", encoding="utf-8") as f:
                            json.dump(state, f, ensure_ascii=False, indent=2, default=str)
                        try: os.remove(tmp)
                        except OSError: pass
                    except Exception:
                        _safe_print(f"[lumen-thinking] Failed to save state after 5 attempts: {e}")
    except Exception as e:
        _safe_print(f"[lumen-thinking] Failed to save state: {e}")

_json_snap_counter = 0'''

new_save = '''def _save_state() -> None:
    """Persist all state to PDB (primary) + JSON snapshot (periodic backup)."""
    global _save_counter, _json_snap_counter
    _save_counter = 0
    _json_snap_counter += 1
    try:
        _pdb_save_all()
        if _JSON_SNAPSHOT_INTERVAL > 0 and _json_snap_counter >= _JSON_SNAPSHOT_INTERVAL:
            _json_snap_counter = 0
            threading.Thread(target=_json_snapshot, daemon=True).start()
    except Exception as e:
        _safe_print(f"[lumen-thinking] Failed to save state: {e}")

_json_snap_counter = 0'''

content = content.replace(old_save, new_save, 1)

# 4) Replace _pdb_snapshot() body with _pdb_save_all
old_pdb_snap_start = 'def _pdb_snapshot() -> None:'
old_pdb_snap_end = 'def _pdb_load_snapshot() -> dict | None:'
idx_start = content.find(old_pdb_snap_start)
idx_end = content.find(old_pdb_snap_end, idx_start)

if idx_start > 0 and idx_end > idx_start:
    new_pdb_save = '''def _pdb_save_all() -> None:
    """Write ALL thinking state to PDB as individual records. Single ACID transaction."""
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
        for i, gp in enumerate(_global_patterns):
            pairs.append(("STATE", f"global:pattern:{i}".encode(), json.dumps(gp).encode()))
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
        meta = {"next_session_num": _next_session_num, "next_niche_id": _next_niche_id,
                "next_task_id": _next_task_id, "saved_at": time.time()}
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
            s = Session.from_dict(info) if isinstance(info, dict) else Session()
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
        obj_meta = {}
        for k, v in globals_data.items():
            if k.startswith("global:objective:") and k != "global:objective_meta":
                gid = k.split(":", 2)[2]; objectives[gid] = v
            elif k == "global:objective_meta":
                obj_meta = v
        if objectives or obj_meta:
            try:
                from objective_loop import load_objective_state
                load_objective_state({"objectives": objectives, "next_objective_id": obj_meta.get("next_id", 1)})
            except ImportError:
                pass
        meta = globals_data.get("global:meta", {})
        _next_session_num = meta.get("next_session_num", 1)
        _next_niche_id = meta.get("next_niche_id", 1)
        _next_task_id = meta.get("next_task_id", 1)
        _safe_print(f"[lumen-thinking] PDB restored: {len(_sessions)} sessions, "
                     f"{sum(len(s.chains) for s in _sessions.values())} chains")
        return True
    except Exception as e:
        _safe_print(f"[lumen-thinking] PDB load FAILED: {e}")
        return False

'''
    content = content[:idx_start] + new_pdb_save + content[idx_end:]
    print('✓ Replaced _pdb_snapshot → _pdb_save_all + _pdb_load_all')
else:
    print(f'✗ Could not find _pdb_snapshot boundaries: {idx_start}-{idx_end}')

# 5) Replace _pdb_load_snapshot → call _pdb_load_all (already done above since it was after)

# 6) Modify _load_state: try PDB first, JSON fallback
old_load = '''def _load_state() -> bool:
    """Restore state from disk. Returns True if state was loaded."""
    global _sessions, _next_session_num, _preserved, _loaded_from_disk
    if not _STATE_FILE.exists():
        _safe_print("[lumen-thinking] No JSON state, trying PDB...")
        pdb = _pdb_load_snapshot()
        if pdb:
            _safe_print("[lumen-thinking] Recovered from PDB snapshot!")
            sess = Session("default")
            sess.chains = pdb.get("chains", {})
            sess.decisions = pdb.get("decisions", [])
            sess.assumptions = pdb.get("assumptions", [])
            sess.works = pdb.get("works", [])
            sess.patterns = pdb.get("patterns", [])
            sess.wiki = pdb.get("wiki", {})
            sess.model = pdb.get("model", {})
            sess.created_at = time.time()
            _sessions["default"] = sess
            if sess.works:
                global _next_work_id
                _next_work_id = max(w["id"] for w in sess.works) + 1
            # Restore objectives from PDB snapshot
            load_objective_state({"objectives": pdb.get("objectives", {}),
                                  "next_objective_id": pdb.get("next_objective_id", 1)})
            return True
        _safe_print("[lumen-thinking] No saved state found — starting fresh.")
        return False'''

new_load = '''def _load_state() -> bool:
    """Restore state from PDB first, then JSON fallback."""
    global _sessions, _next_session_num, _preserved, _loaded_from_disk

    # PDB first (primary storage)
    if _pdb_load_all():
        _loaded_from_disk = True
        _safe_print("[lumen-thinking] State restored from PDB")
        return True

    # JSON fallback
    if not _STATE_FILE.exists():
        _safe_print("[lumen-thinking] No saved state found — starting fresh.")
        return False'''

content = content.replace(old_load, new_load, 1)

# 7) Add _json_snapshot function (insert before _load_state)
json_snap_func = '''

def _json_snapshot() -> None:
    """Periodic JSON snapshot for backup. Runs in daemon thread every _JSON_SNAPSHOT_INTERVAL saves."""
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
        _safe_print(f"[lumen-thinking] JSON snapshot saved")
    except Exception as e:
        _safe_print(f"[lumen-thinking] JSON snapshot FAILED: {e}")

'''

# Insert before the _load_state we just replaced
load_idx = content.find('\ndef _load_state() -> bool:')
if load_idx > 0:
    content = content[:load_idx] + json_snap_func + content[load_idx:]
    print('✓ _json_snapshot inserted before _load_state')
else:
    print('✗ Could not find _load_state')

with open(p, 'w') as f:
    f.write(content)

import py_compile
try:
    py_compile.compile(p, doraise=True)
    print('✓ Syntax OK')
except py_compile.PyCompileError as e:
    print(f'✗ Error: {e}')
