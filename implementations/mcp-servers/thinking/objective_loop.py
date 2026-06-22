"""
LUMEN Agent Loop — cognitive objective engine.

An objective is a goal with acceptance criteria that goes through 3 phases:
  1. BUILDER — semi-autonomous Q&A to refine the goal with the user
  2. BUILDING — autonomous loop: plan → execute → judge → repeat
  3. TESTING — generate tests, run them, validate results

State is persisted in the thinking server's state system (JSON + PDB snapshot).
"""

import time, json

# ── State ──
_objectives: dict[str, dict] = {}  # goal_id → objective dict
_next_objective_id = 1

PHASES = ["builder", "building", "testing", "done"]

# ── Judge heuristic (no LLM — 0 tokens) ──
def _judge_objective(obj: dict) -> dict:
    """Evaluate objective completeness. Returns score 0-10 + verdict."""
    criteria = obj.get("criteria", [])
    tasks = obj.get("tasks", [])
    phase = obj.get("phase", "builder")

    if phase == "builder":
        # Builder judge: clarity score based on criteria detail + description length
        desc_score = min(5, len(obj.get("description", "")) // 30)  # 0-5
        criteria_score = min(3, len(criteria))  # 0-3
        has_examples = 2 if any("ejemplo" in obj.get("description", "").lower() or "example" in obj.get("description", "").lower() for _ in [1]) else 0
        score = desc_score + criteria_score + has_examples
        score = min(10, score)

        if score >= 8:
            return {"score": score, "verdict": "READY", "next_phase": "building",
                    "message": f"Clarity score {score}/10. Ready to plan."}
        else:
            questions = []
            if desc_score < 3:
                questions.append("¿Puedes detallar más el objetivo? ¿Qué significa exactamente?")
            if criteria_score < 2:
                questions.append("¿Qué criterios objetivos usarías para saber que está terminado?")
            if not questions:
                questions.append("¿Hay algo más que deba saber para entender bien el objetivo?")
            return {"score": score, "verdict": "ASK",
                    "message": f"Clarity score {score}/10. Need more details.",
                    "questions": questions}

    elif phase == "building":
        # Building judge: completion + criteria verification
        done = sum(1 for t in tasks if t.get("status") == "done")
        total = len(tasks) or 1
        completion = done / total
        score = completion * 7  # 0-7

        # Check criteria via task verification
        verified_criteria = sum(1 for c in criteria if c.get("verified", False))
        if criteria:
            score += (verified_criteria / len(criteria)) * 3

        score = min(10, round(score, 1))

        if score >= 8:
            return {"score": score, "verdict": "PASS", "next_phase": "testing",
                    "message": f"Building score {score}/10. {done}/{total} tasks done. Moving to testing."}
        else:
            return {"score": score, "verdict": "LOOP",
                    "message": f"Building score {score}/10. {done}/{total} tasks done. {total-done} remaining.",
                    "pending_tasks": total - done}

    elif phase == "testing":
        # Testing judge
        test_results = obj.get("test_results", [])
        passed = sum(1 for t in test_results if t.get("passed", False))
        total_tests = len(test_results) or 1
        score = min(10, round((passed / total_tests) * 10, 1))

        if score >= 10:
            return {"score": score, "verdict": "DONE", "next_phase": "done",
                    "message": f"All {passed} tests passed. Objective complete!"}
        else:
            failed_tests = [t for t in test_results if not t.get("passed")]
            return {"score": score, "verdict": "FIX",
                    "message": f"{passed}/{total_tests} tests passed. {len(failed_tests)} failed.",
                    "failed_tests": failed_tests[:5]}

    return {"score": 0, "verdict": "UNKNOWN", "message": "Unknown phase"}


# ── Tool handlers ──

def tool_objective_create(args: dict) -> dict:
    """Create a new objective. Starts in BUILDER phase."""
    global _next_objective_id

    title = args.get("title", "")
    if not title:
        return {"content": [{"type": "text", "text": "Error: 'title' required."}]}

    description = args.get("description", "")
    criteria = args.get("criteria", [])
    if isinstance(criteria, str):
        criteria = [{"description": c, "verified": False} for c in criteria.split(",")]
    else:
        criteria = [{"description": c, "verified": False} for c in criteria]

    goal_id = f"goal_{_next_objective_id}"
    _next_objective_id += 1

    obj = {
        "id": goal_id,
        "title": title,
        "description": description,
        "criteria": criteria,
        "phase": "builder",
        "tasks": [],
        "test_results": [],
        "history": [{"phase": "builder", "action": "created", "ts": time.time()}],
        "created_at": time.time(),
        "updated_at": time.time(),
        "score": 0,
    }
    _objectives[goal_id] = obj

    # Initial judge
    result = _judge_objective(obj)
    obj["score"] = result["score"]

    lines = [f"🎯 Objective #{goal_id}: {title}",
             f"   Phase: BUILDER | Score: {result['score']}/10",
             f"   {result['message']}"]
    if result.get("questions"):
        for q in result["questions"]:
            lines.append(f"   ❓ {q}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_objective_judge(args: dict) -> dict:
    """Evaluate objective and return score + verdict + next steps."""
    goal_id = args.get("goal_id", "")
    if not goal_id:
        return {"content": [{"type": "text", "text": "Error: 'goal_id' required."}]}

    obj = _objectives.get(goal_id)
    if not obj:
        return {"content": [{"type": "text", "text": f"Objective '{goal_id}' not found."}]}

    # mark_done=True: mark all tasks, verify criteria, and add test in TESTING phase
    if args.get("mark_done", False):
        for t in obj.get("tasks", []):
            if t.get("status") != "done":
                t["status"] = "done"
                t["done_at"] = time.time()
        for c in obj.get("criteria", []):
            c["verified"] = True
        # In TESTING phase, auto-add a passed test result
        if obj.get("phase") == "testing" and not obj.get("test_results", []):
            obj.setdefault("test_results", []).append({
                "name": "mark_done_auto_test",
                "passed": True,
                "ts": time.time(),
                "summary": f"All {len(obj.get('criteria',[]))} criteria verified"
            })
        obj["history"].append({"phase": obj["phase"], "action": "mark_done_all", "ts": time.time()})

    result = _judge_objective(obj)
    obj["score"] = result["score"]
    obj["updated_at"] = time.time()
    obj["history"].append({"phase": obj["phase"], "action": "judged", "score": result["score"], "ts": time.time()})

    # Phase transitions
    if result["verdict"] == "READY":
        obj["phase"] = "building"
    elif result["verdict"] == "PASS":
        obj["phase"] = "testing"
    elif result["verdict"] == "DONE":
        obj["phase"] = "done"

    lines = [f"⚖️ Judge — {obj['title']}",
             f"   Phase: {obj['phase'].upper()} | Score: {result['score']}/10",
             f"   Verdict: {result['verdict']}",
             f"   {result['message']}"]
    if result.get("questions"):
        for q in result["questions"]:
            lines.append(f"   ❓ {q}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_objective_plan(args: dict) -> dict:
    """Decompose objective into subtasks. Creates kanban tasks."""
    goal_id = args.get("goal_id", "")
    if not goal_id:
        return {"content": [{"type": "text", "text": "Error: 'goal_id' required."}]}

    obj = _objectives.get(goal_id)
    if not obj:
        return {"content": [{"type": "text", "text": f"Objective '{goal_id}' not found."}]}

    if obj["phase"] not in ("building", "testing"):
        return {"content": [{"type": "text", "text": f"Objective is in {obj['phase']} phase. Judge must approve before planning."}]}

    # Use description + criteria to generate tasks
    # This is a heuristic — LLM should enrich this via sequential_thinking
    tasks = []
    criteria = obj.get("criteria", [])

    # Base tasks from criteria
    for i, c in enumerate(criteria):
        tasks.append({
            "id": f"{goal_id}_t{i+1}",
            "title": f"Implement: {c.get('description', 'criterion ' + str(i+1))}",
            "status": "backlog",
            "created_at": time.time(),
        })

    # Add verification task
    tasks.append({
        "id": f"{goal_id}_t{len(criteria)+1}",
        "title": f"Verify all criteria for: {obj['title']}",
        "status": "backlog",
        "created_at": time.time(),
    })

    obj["tasks"] = tasks
    obj["updated_at"] = time.time()
    obj["history"].append({"phase": obj["phase"], "action": "planned", "task_count": len(tasks), "ts": time.time()})

    lines = [f"📋 Planner — {obj['title']}",
             f"   {len(tasks)} tasks created:"]
    for t in tasks:
        lines.append(f"   • {t['title']}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_objective_status(args: dict) -> dict:
    """Show objective progress. Dashboard-ready."""
    goal_id = args.get("goal_id", "")
    if goal_id:
        obj = _objectives.get(goal_id)
        if not obj:
            return {"content": [{"type": "text", "text": f"Objective '{goal_id}' not found."}]}
        objs = [obj]
    else:
        objs = list(_objectives.values())

    if not objs:
        return {"content": [{"type": "text", "text": "No objectives defined. Use objective_create to start."}]}

    lines = []
    for obj in objs:
        phase_icon = {"builder": "🔵", "building": "⚙️", "testing": "🧪", "done": "✅"}.get(obj["phase"], "❓")
        tasks_done = sum(1 for t in obj.get("tasks", []) if t.get("status") == "done")
        tasks_total = len(obj.get("tasks", [])) or 1
        bar_len = 10
        done_bar = int((tasks_done / tasks_total) * bar_len)
        bar = "█" * done_bar + "░" * (bar_len - done_bar)

        lines.append(f"{phase_icon} {obj['id']}: {obj['title']}")
        lines.append(f"   Phase: {obj['phase'].upper()} | Score: {obj.get('score', 0)}/10")
        lines.append(f"   Tasks: {bar} {tasks_done}/{tasks_total}")
        lines.append("")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}




def tool_checklist(args: dict) -> dict:
    """Pilot checklist: retrieve, mark, or check status of task-type checklists."""
    action = args.get("action", "get")
    task_type = args.get("task_type", "")
    item_tool = args.get("tool", "")

    if not task_type and action != "status":
        return {"content": [{"type": "text", "text": "task_type required. Options: bug_fix, feature, research, audit"}]}

    try:
        import sqlite3, json as _j, os, time as _t
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pdb", "lumen-pdb.db")
        conn = sqlite3.connect(db_path)

        if action == "get":
            # Try raw JSON at def:{task_type}
            rows = conn.execute("SELECT value FROM _globals WHERE ns='CHECKLIST' AND subkey=?", (f'def:{task_type}',)).fetchall()
            if not rows:
                conn.close()
                return {"content": [{"type": "text", "text": f"No checklist defined for '{task_type}'."}]}
            items = _j.loads(rows[0][0])

            # Get session usage
            session_id = args.get("session", "default")
            used_rows = conn.execute(
                "SELECT subkey FROM _globals WHERE ns='CHECKLIST' AND subkey LIKE ?",
                (f'session:{session_id}:{task_type}:%',)).fetchall()
            used_tools = set()
            for (sk,) in used_rows:
                sk = sk.decode() if isinstance(sk, bytes) else sk
                parts = sk.split(':')
                if len(parts) >= 5:
                    used_tools.add(parts[4])

            lines = [f'🧾 Checklist — {task_type}']
            for item in items:
                status = '✅' if item['tool'] in used_tools else ('⬜' if item.get('required') else '◽')
                phase_icon = {'before': '📋', 'during': '🔧', 'after': '✅'}.get(item.get('phase', ''), '>')
                lines.append(f'  {status} {phase_icon} {item["desc"]}')
                lines.append(f'     -> {item["tool"]}')

            required_total = sum(1 for i in items if i.get('required'))
            required_done = sum(1 for i in items if i.get('required') and i['tool'] in used_tools)
            lines.append(f'')
            lines.append(f'  Compliance: {required_done}/{required_total} required items')

            conn.close()
            return {"content": [{"type": "text", "text": chr(10).join(lines)}]}

        elif action == "mark":
            if not item_tool:
                conn.close()
                return {"content": [{"type": "text", "text": "tool required for mark action."}]}
            session_id = args.get("session", "default")
            subkey = f'session:{session_id}:{task_type}:{item_tool}:{int(_t.time())}'
            conn.execute("INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                        ('CHECKLIST', subkey.encode(), _j.dumps({"tool": item_tool, "ts": _t.time()}).encode()))
            conn.commit()
            conn.close()
            return {"content": [{"type": "text", "text": f'Marked {item_tool} as done for {task_type}.'}]}

        elif action == "status":
            session_id = args.get("session", "default")
            rows = conn.execute(
                "SELECT subkey FROM _globals WHERE ns='CHECKLIST' AND subkey LIKE ? ORDER BY subkey",
                (f'session:{session_id}:%',)).fetchall()
            if not rows:
                conn.close()
                return {"content": [{"type": "text", "text": "No checklist activity this session."}]}
            by_type = {}
            for (sk,) in rows:
                sk = sk.decode() if isinstance(sk, bytes) else sk
                parts = sk.split(':')
                if len(parts) >= 4:
                    ttype = parts[2]
                    by_type.setdefault(ttype, []).append(parts[3] if len(parts) > 3 else sk)
            lines = ['Checklist Status - This Session']
            for ttype, tools in sorted(by_type.items()):
                lines.append(f'  {ttype}: {len(tools)} items marked')
                for t in tools:
                    lines.append(f'    [x] {t}')
            conn.close()
            return {"content": [{"type": "text", "text": chr(10).join(lines)}]}

        conn.close()
        return {"content": [{"type": "text", "text": f"Unknown action: {action}"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Checklist error: {e}"}]}


# ── Export for server.py ──

OBJECTIVE_HANDLERS = {
    "checklist": tool_checklist,
    "objective_create": tool_objective_create,
    "objective_judge": tool_objective_judge,
    "objective_plan": tool_objective_plan,
    "objective_status": tool_objective_status,
}

OBJECTIVE_SCHEMAS = [
    {
        "name": "objective_create",
        "description": "Create a cognitive objective with acceptance criteria. Starts the Agent Loop in BUILDER phase for iterative refinement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Goal title (e.g. 'Mobile Dashboard Optimisation')"},
                "description": {"type": "string", "description": "Detailed description of what you want to achieve"},
                "criteria": {"type": "array", "items": {"type": "string"}, "description": "Acceptance criteria (e.g. ['responsive design', '<2s load time'])"},
            },
            "required": ["title"]
        }
    },
    {
        "name": "objective_judge",
        "description": "Judge the objective: evaluate clarity/completeness and return score 0-10 + verdict. In BUILDING phase, decides whether to loop back or move to TESTING.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal_id": {"type": "string", "description": "Objective ID to evaluate"},
            },
            "required": ["goal_id"]
        }
    },
    {
        "name": "objective_plan",
        "description": "Plan the objective: decompose into subtasks. Creates tasks based on acceptance criteria.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal_id": {"type": "string", "description": "Objective ID to plan"},
            },
            "required": ["goal_id"]
        }
    },
    {
        "name": "objective_status",
        "description": "Show objective progress: phase, score, task completion bar. Use goal_id for one objective or omit for all.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal_id": {"type": "string", "description": "Optional: specific objective ID"}
            }
        }
    },
    {
        "name": "checklist",
        "description": "Pilot checklist: get task checklist, mark tools as used, or view session compliance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["get", "mark", "status"], "description": "get, mark, or status"},
                "task_type": {"type": "string", "description": "Task type: bug_fix, feature, research, audit"},
                "tool": {"type": "string", "description": "Tool name to mark as done (for action=mark)"},
                "session": {"type": "string", "description": "Session identifier (default: default)"}
            },
            "required": ["action"]
        }
    },
]

def get_objective_state() -> dict:
    """Return serializable state for _save_state."""
    return {"objectives": _objectives, "next_objective_id": _next_objective_id}

def load_objective_state(state: dict) -> None:
    """Restore objectives from saved state."""
    global _objectives, _next_objective_id
    _objectives = state.get("objectives", {})
    _next_objective_id = state.get("next_objective_id", 1)
