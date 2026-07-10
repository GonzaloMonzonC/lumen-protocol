#!/usr/bin/env python3
"""LUMEN Cognitive Dashboard API v3 — standalone. Puerto 9878.
Lee/escribe .thinking_state.json. CORS habilitado para el HTML.
"""
import json, time, os, sys
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS

BASE = Path(__file__).parent
STATE_FILE = BASE / ".thinking_state.json"

app = Flask(__name__)
CORS(app)

def _load():
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except: pass
    return {}

def _save(data):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _get_model(s):
    # Collect model from all sessions
    model = {}
    for sess in s.get("sessions", {}).values():
        m = sess.get("model", {})
        if isinstance(m, dict):
            model.update(m)
    return model

# ── Wiki Editor ──
@app.route("/model", methods=["GET"])
def model_get():
    s = _load()
    model = _get_model(s)
    entity = request.args.get("entity")
    if entity:
        ent = model.get(entity)
        if ent:
            ent["name"] = entity
            return jsonify(ent)
        return jsonify({"error":"not found"}), 404
    return jsonify({"entities": list(model.keys()), "count": len(model), "data": model})

@app.route("/model", methods=["POST"])
def model_post():
    s = _load()
    d = request.get_json(force=True)
    name = d.get("entity","")
    if not name:
        return jsonify({"error":"entity required"}), 400
    for sess in s.get("sessions", {}).values():
        if "model" not in sess:
            sess["model"] = {}
        sess["model"][name] = {
            "deps": d.get("deps", []),
            "role": d.get("role", ""),
            "notes": d.get("notes", ""),
            "properties": d.get("properties", {}),
            "created_at": time.time(),
        }
        break
    _save(s)
    return jsonify({"ok": True, "entity": name}), 201

@app.route("/model/<name>", methods=["DELETE"])
def model_delete(name):
    s = _load()
    found = False
    for sess in s.get("sessions", {}).values():
        if name in sess.get("model", {}):
            del sess["model"][name]
            found = True
            break
    if not found:
        return jsonify({"error":"not found"}), 404
    _save(s)
    return jsonify({"ok": True})

@app.route("/model/stats")
def model_stats():
    s = _load()
    model = _get_model(s)
    return jsonify({"count": len(model), "names": list(model.keys())})

# ── Sessions ──
@app.route("/sessions")
def sessions_list():
    s = _load()
    items = []
    for sid, sess in s.get("sessions", {}).items():
        items.append({"id": sid, "label": sess.get("label",""), "chains": len(sess.get("chains",{})), "tool_calls": sess.get("tool_calls",0)})
    return jsonify({"count": len(items), "sessions": items})

@app.route("/sessions/<sid>")
def sessions_detail(sid):
    s = _load()
    sess = s.get("sessions", {}).get(sid)
    if not sess: return jsonify({"error":"not found"}), 404
    return jsonify({"id": sid, "label": sess.get("label"), "chains": list(sess.get("chains",{}).keys()), "tool_calls": sess.get("tool_calls",0)})

# ── Collisions ──
@app.route("/collisions")
def collisions():
    s = _load()
    window = int(request.args.get("window", 300))
    now = time.time()
    ft = s.get("file_touches", [])
    by_file = {}
    for t in ft:
        if now - t.get("timestamp", 0) < window:
            p = t.get("path", "?")
            by_file.setdefault(p, set()).add(t.get("session_id", "?"))
    colls = [{"path": p, "sessions": list(ss)} for p, ss in by_file.items() if len(ss) > 1]
    return jsonify({"collisions": colls, "window_s": window})

# ── Timeline ──
@app.route("/timeline")
def timeline():
    s = _load()
    limit = int(request.args.get("limit", 50))
    events = []
    for sid, sess in s.get("sessions", {}).items():
        for cid, chain in sess.get("chains", {}).items():
            for t in chain.get("thoughts", []):
                events.append({"ts": t.get("timestamp",0), "session": sid, "type": "thought", "chain": cid, "text": t.get("thought","")[:120]})
    events.sort(key=lambda e: e["ts"], reverse=True)
    return jsonify(events[:limit])

# ── Inbox ──
@app.route("/inbox", methods=["GET"])
def inbox_get():
    s = _load()
    sid = request.args.get("session", "default")
    msgs = [m for m in s.get("messages",[]) if m.get("to_session") in (sid, "*")]
    return jsonify({"count": len(msgs), "messages": msgs})

@app.route("/inbox", methods=["POST"])
def inbox_post():
    s = _load()
    d = request.get_json(force=True)
    msg = {"to_session": d.get("to","default"), "from_session": d.get("from","dashboard"), "text": d.get("text",""), "timestamp": int(time.time()), "read": False}
    s.setdefault("messages", []).append(msg)
    s["messages"] = s["messages"][-200:]
    _save(s)
    return jsonify({"ok": True}), 201

@app.route("/inbox/mark-read", methods=["POST"])
def inbox_mark_read():
    s = _load()
    d = request.get_json(force=True)
    mid = d.get("message_id")
    sid = d.get("session", "default")
    msgs = s.get("messages", [])
    if mid is not None and mid < len(msgs):
        msgs[mid]["read"] = True
        _save(s)
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=9878, debug=False)
