"""
PDB-First Persistence — script to modify server.py

Changes:
1. Replace _save_state() with PDB-first version
2. Replace _pdb_snapshot() with _json_snapshot() (periodic JSON backup)
3. Replace _pdb_load_snapshot() with _pdb_load_all() (read from PDB)
4. Modify _load_state() to try PDB first, JSON fallback
5. Adjust _pdb_snap_counter → _json_snap_counter, interval 50
"""
import re

path = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking\server.py'
with open(path) as f:
    content = f.read()

# ── Constants change ──
content = content.replace(
    '_PDB_SNAPSHOT_INTERVAL = 5  # PDB snapshot every N saves (0=disable)',
    '_JSON_SNAPSHOT_INTERVAL = 50  # JSON snapshot every N saves (0=disable)'
)

# ── Replace _save_state() with PDB-first version ──
old_save = '''def _save_state() -> None:
    """Persist all state to disk atomically."""
    global _save_counter, _pdb_snap_counter
    _save_counter = 0
    _pdb_snap_counter += 1
    if _PDB_SNAPSHOT_INTERVAL > 0 and _pdb_snap_counter >= _PDB_SNAPSHOT_INTERVAL:
        _pdb_snap_counter = 0
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

_pdb_snap_counter = 0'''

new_save = '''def _save_state() -> None:
    """Persist all state to PDB (primary) + optionally JSON snapshot."""
    global _save_counter, _json_snap_counter
    _save_counter = 0
    _json_snap_counter += 1

    try:
        # 1) PDB: write all current state as individual records
        _pdb_save_all()

        # 2) JSON snapshot (periodic backup)
        if _JSON_SNAPSHOT_INTERVAL > 0 and _json_snap_counter >= _JSON_SNAPSHOT_INTERVAL:
            _json_snap_counter = 0
            threading.Thread(target=_json_snapshot, daemon=True).start()
    except Exception as e:
        _safe_print(f"[lumen-thinking] Failed to save state: {e}")

_json_snap_counter = 0

def _pdb_save_all() -> None:
    """Write ALL state to PDB as individual records. ACID via single transaction."""
    try:
        conn = sqlite3.connect(str(_PDB_PATH))
        # Clear previous STATE namespace
        conn.execute("DELETE FROM _globals WHERE ns='STATE'")
        pairs = []

        # ── Session data ──
        for sid, sess in _sessions.items():
            # Session info
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

        # ── Module-level state ──
        # Preserved contexts
        for i, p in enumerate(_preserved):
            pairs.append(("STATE", f"global:preserved:{i}".encode(), json.dumps(p).encode()))
        # Timeline
        for i, t in enumerate(_call_timeline):
            pairs.append(("STATE", f"global:timeline:{i}".encode(), json.dumps(t).encode()))
        # File touches
        for i, ft in enumerate(_file_touches):
            pairs.append(("STATE", f"global:file_touch:{i}".encode(), json.dumps(ft).encode()))
        # File claims
        for path, claim in _file_claims.items():
            pairs.append(("STATE", f"global:file_claim:{path}".encode(), json.dumps(claim).encode()))
        # Agent messages
        for i, m in enumerate(_agent_messages):
            pairs.append(("STATE", f"global:agent_msg:{i}".encode(), json.dumps(m).encode()))
        # Global patterns
        for i, p in enumerate(_global_patterns):
            pairs.append(("STATE", f"global:pattern:{i}".encode(), json.dumps(p).encode()))
        # Web snapshots
        for sid, snap in _web_snapshots.items():
            pairs.append(("STATE", f"global:web_snapshot:{sid}".encode(), json.dumps(snap).encode()))
        # Q&A pairs
        for qid, qa in _qa_pairs.items():
            pairs.append(("STATE", f"global:qa:{qid}".encode(), json.dumps(qa).encode()))
        # Niches
        for nid, niche in _niches.items():
            pairs.append(("STATE", f"global:niche:{nid}".encode(), json.dumps(niche).encode()))
        # Tasks
        for tid, task in _tasks.items():
            pairs.append(("STATE", f"global:task:{tid}".encode(), json.dumps(task).encode()))
        # Objectives (from objective_loop module)
        try:
            from objective_loop import _objectives, _next_objective_id
            for gid, obj in _objectives.items():
                pairs.append(("STATE", f"global:objective:{gid}".encode(), json.dumps(obj).encode()))
            pairs.append(("STATE", "global:objective_meta".encode(), json.dumps({"next_id": _next_objective_id}).encode()))
        except ImportError:
            pass

        # Global metadata
        meta = {
            "next_session_num": _next_session_num,
            "next_niche_id": _next_niche_id,
            "next_task_id": _next_task_id,
            "saved_at": time.time(),
        }
        pairs.append(("STATE", "global:meta".encode(), json.dumps(meta).encode()))

        conn.executemany("INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)", pairs)
        conn.commit()
        conn.close()
    except Exception as e:
        _safe_print(f"[lumen-thinking] PDB save FAILED: {e}")

def _pdb_load_all() -> bool:
    """Load ALL state from PDB. Returns True if state was loaded."""
    global _sessions, _next_session_num, _preserved, _call_timeline
    global _session_presence, _file_touches, _file_claims
    global _agent_messages, _global_patterns, _web_snapshots, _qa_pairs
    global _niches, _tasks, _next_niche_id, _next_task_id
    try:
        if not _PDB_PATH.exists():
            return False
        conn = sqlite3.connect(str(_PDB_PATH))
        rows = conn.execute("SELECT subkey, value FROM _globals WHERE ns='STATE'").fetchall()
        conn.close()
        if not rows:
            return False

        # Decode all rows
        records = {}
        for sk, val in rows:
            sk = sk.decode() if isinstance(sk, bytes) else sk
            val = json.loads(val.decode() if isinstance(val, bytes) else val)
            records[sk] = val

        # Group by prefix
        sessions_data = {}
        globals_data = {}

        for sk, val in records.items():
            if sk.startswith("session:"):
                parts = sk.split(":", 3)
                if len(parts) >= 3:
                    sid = parts[1]
                    if sid not in sessions_data:
                        sessions_data[sid] = {"chains": {}, "assumptions": [], "decisions": [],
                                              "works": [], "patterns": [], "model": {}, "wiki": {},
                                              "bridges": []}
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
                    elif sub == "bridge":
                        sessions_data[sid]["bridges"].append(val)
            elif sk.startswith("global:"):
                globals_data[sk] = val

        # Reconstruct sessions
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

        # Reconstruct globals
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

        # Objectives
        objectives = {}
        objective_meta = {}
        for k, v in globals_data.items():
            if k.startswith("global:objective:") and k != "global:objective_meta":
                gid = k.split(":", 2)[2]
                objectives[gid] = v
            elif k == "global:objective_meta":
                objective_meta = v
        if objectives or objective_meta:
            try:
                from objective_loop import load_objective_state
                load_objective_state({"objectives": objectives, "next_objective_id": objective_meta.get("next_id", 1)})
            except ImportError:
                pass

        # Metadata
        meta = globals_data.get("global:meta", {})
        _next_session_num = meta.get("next_session_num", 1)
        _next_niche_id = meta.get("next_niche_id", 1)
        _next_task_id = meta.get("next_task_id", 1)

        _safe_print(f"[lumen-thinking] PDB state restored: {len(_sessions)} sessions, "
                     f"{sum(len(s.chains) for s in _sessions.values())} chains, "
                     f"{sum(len(s.patterns) for s in _sessions.values())} patterns, "
                     f"{len(_niches)} niches, {len(_tasks)} tasks, {len(objectives)} objectives")
        return True
    except Exception as e:
        _safe_print(f"[lumen-thinking] PDB load FAILED: {e}")
        return False

def _json_snapshot() -> None:
    """Periodic JSON snapshot for backup/portability. Runs in daemon thread."""
    try:
        # Build state dict (same as old _save_state but without rewrite on every call)
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
    except Exception as e:
        _safe_print(f"[lumen-thinking] JSON snapshot FAILED: {e}")'''

content = content.replace(old_save, new_save, 1)

# ── Modify _load_state() to try PDB first ──
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
        # Recompute global assumption ID counter to avoid collisions after restore
        max_id = 0
        for s in _sessions.values():
            for a in s.assumptions:
                if a.get("id", 0) > max_id:
                    max_id = a["id"]
        global _next_assumption_id
        _next_assumption_id = max_id + 1
        _safe_print(f"[lumen-thinking] State restored: {total_chains} chains, {total_patterns} patterns, "
                     f"{len(_preserved)} preserved items across {len(_sessions)} sessions "
                     f"(saved {saved_at})")
        return True
    except Exception as e:
        _safe_print(f"[lumen-thinking] Failed to load state: {e} — starting fresh.")
        return False'''

new_load = '''def _load_state() -> bool:
    """Restore state from PDB first, then JSON fallback."""
    global _sessions, _next_session_num, _preserved, _loaded_from_disk

    # 1) Try PDB first (primary storage)
    if _pdb_load_all():
        _loaded_from_disk = True
        _safe_print("[lumen-thinking] State restored from PDB")
        return True

    # 2) Try JSON as fallback (legacy / backup)
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
        return False'''

content = content.replace(old_load, new_load, 1)

# ── Remove old _pdb_snapshot and _pdb_load_snapshot (replaced by _pdb_save_all/_pdb_load_all) ──
# Find and delete the old functions
old_snapshot = '''def _pdb_snapshot() -> None:
    """Write thinking state to PDB. Runs in daemon thread, 0 LLM tokens.\""""
    try:
        conn = sqlite3.connect(str(_PDB_PATH))
        conn.execute("DELETE FROM _globals WHERE ns='SNAPSHOT'")
        now = time.time()
        pairs = []
        for sid, sess in _sessions.items():
            for cid, chain in sess.chains.items():
                v = json.dumps(chain)
                pairs.append(("SNAPSHOT", f"c:{cid}".encode(), v.encode()))
            for d in sess.decisions:
                v = json.dumps(d)
                pairs.append(("SNAPSHOT", f"d:{d['id']}".encode(), v.encode()))
            for a in sess.assumptions:
                v = json.dumps(a)
                pairs.append(("SNAPSHOT", f"a:{a['id']}".encode(), v.encode()))
            for w in sess.works:
                v = json.dumps(w)
                pairs.append(("SNAPSHOT", f"w:{w['id']}".encode(), v.encode()))
            for pat in sess.patterns:
                v = json.dumps(pat)
                pairs.append(("SNAPSHOT", f"p:{pat.get('name','?')}".encode(), v.encode()))
            for title, page in sess.wiki.items():
                v = json.dumps(page)
                pairs.append(("SNAPSHOT", f"wiki:{title}".encode(), v.encode()))
            for name, entity in sess.model.items():
                v = json.dumps(entity)
                pairs.append(("SNAPSHOT", f"m:{name}".encode(), v.encode()))
        # Save objectives at module level (not per-session)
        from objective_loop import _objectives, _next_objective_id
        pairs.append(("SNAPSHOT", "objective:state".encode(), json.dumps({"objectives": _objectives, "next_objective_id": _next_objective_id}).encode()))
        conn.executemany("INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)", pairs)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[lumen-thinking] PDB snapshot FAILED: {e}", file=sys.stderr)


def _pdb_load_snapshot() -> dict | None:
    """Recover state from PDB backup. Returns None if no backup found.\""""
    try:
        if not _PDB_PATH.exists():
            return None
        conn = sqlite3.connect(str(_PDB_PATH))
        rows = conn.execute("SELECT subkey, value FROM _globals WHERE ns='SNAPSHOT'").fetchall()
        conn.close()
        if not rows:
            return None
        chains, decisions, assumptions, works, patterns, wiki, model = {}, [], [], [], [], [], {}, {}
        objectives = {}
        next_obj_id = 1
        for sk, val in rows:
            sk = sk.decode() if isinstance(sk, bytes) else sk
            val = val.decode() if isinstance(val, bytes) else val
            try:
                v = json.loads(val)
            except Exception:
                continue
            if sk.startswith("c:"):
                chains[sk[2:]] = v
            elif sk.startswith("d:"):
                decisions.append(v)
            elif sk.startswith("a:"):
                assumptions.append(v)
            elif sk.startswith("w:"):
                works.append(v)
            elif sk.startswith("p:"):
                patterns.append(v)
            elif sk.startswith("wiki:"):
                wiki[sk[5:]] = v
            elif sk.startswith("m:"):
                model[sk[2:]] = v
            elif sk == "objective:state":
                objectives = v.get("objectives", {})
                next_obj_id = v.get("next_objective_id", 1)
        return {"chains": chains, "decisions": decisions, "assumptions": assumptions,
                "works": works, "patterns": patterns, "wiki": wiki, "model": model,
                "objectives": objectives, "next_objective_id": next_obj_id}
    except Exception as e:
        print(f"[lumen-thinking] PDB load FAILED: {e}", file=sys.stderr)
        return None'''

# Check if old functions still exist
if 'def _pdb_snapshot' in content:
    # Find exact location of old _pdb_snapshot
    start = content.find('def _pdb_snapshot')
    # Find the end (next def or module-level line)
    end = content.find('\ndef _pdb_load_snapshot', start)
    if end < 0:
        end = content.find('\ndef _load_state', start)
    if end > start:
        content = content[:start] + '\n' + content[end:]
    print("Removed old _pdb_snapshot")
else:
    print(" _pdb_snapshot already replaced")

# Verify syntax
import py_compile
try:
    py_compile.compile(path, doraise=True)
    print('✓ All changes applied, syntax OK')
except py_compile.PyCompileError as e:
    print(f'✗ Syntax error: {e}')
    # Save the patched file for debugging
    with open(path, 'w') as f:
        f.write(content)
    print('File saved for debugging')

with open(path, 'w') as f:
    f.write(content)
print('✓ server.py saved')
