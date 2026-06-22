"""
LUMEN Kanban Module — Niche & Task management tools.

Extracted from server.py for modularity. Follows the same pattern
as objective_loop.py: exports KANBAN_HANDLERS and KANBAN_SCHEMAS
that server.py merges into its HANDLERS and TOOLS dicts.
"""

import json
import time
import re as _re
from typing import Any

# ── Late imports (avoid circular dep with server.py) ──
# _get_session, _niches, _tasks, _next_niche_id, _next_task_id, _auto_save, _pdb_save_all
# are imported inside each handler via "from server import ..."

# ═══════════════════════════════════════════════════════════════════════
# Niche tools
# ═══════════════════════════════════════════════════════════════════════

def kanban_tool_niche_create(args: dict) -> dict:
    from server import _niches, _next_niche_id, _save_state
    name = args.get("name", "").strip()
    if not name:
        return {"content": [{"type": "text", "text": "Error: 'name' required."}]}
    color = args.get("color", "#22d3ee")
    desc = args.get("desc", "")
    columns = args.get("columns", ["Backlog", "In Progress", "Review", "Done", "Blocked"])
    nid = f"niche_{_next_niche_id}"
    _next_niche_id += 1
    _niches[nid] = {
        "id": nid, "name": name, "color": color, "desc": desc,
        "columns": columns, "archived": False, "created_at": time.time(),
    }
    _save_state()
    return {"content": [{"type": "text", "text": f"✅ Niche created: {name} (ID: {nid})"}]}


def kanban_tool_niche_list(args: dict) -> dict:
    from server import _niches
    if not _niches:
        return {"content": [{"type": "text", "text": "No niches defined. Use niche_create."}]}
    lines = [f"📋 Niches ({len(_niches)}):"]
    for nid, n in _niches.items():
        archived = " 📦" if n.get("archived") else ""
        tc = sum(1 for t in _tasks.values() if t.get("niche_id") == nid) if '_tasks' in dir() else "?"
        lines.append(f"  • {n['name']} (ID: {nid}){archived}")
        lines.append(f"    Color: {n.get('color','#?')} · Columns: {len(n.get('columns',[]))} · Tasks: {tc}")
        if n.get("desc"):
            lines.append(f"    {n['desc'][:80]}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def kanban_tool_niche_update(args: dict) -> dict:
    from server import _niches, _save_state
    nid = args.get("niche_id", "")
    if nid not in _niches:
        return {"content": [{"type": "text", "text": f"Niche '{nid}' not found."}]}
    n = _niches[nid]
    for k in ("name", "color", "desc"):
        if k in args and args[k] is not None:
            n[k] = args[k]
    if "archived" in args:
        n["archived"] = args["archived"]
    _save_state()
    return {"content": [{"type": "text", "text": f"✅ Niche '{nid}' updated: {n.get('name','?')}"}]}


# ═══════════════════════════════════════════════════════════════════════
# Task tools
# ═══════════════════════════════════════════════════════════════════════

def kanban_tool_task_create(args: dict) -> dict:
    from server import _tasks, _next_task_id, _niches, _save_state
    nid = args.get("niche_id", "")
    title = args.get("title", "").strip()
    if not nid or not title:
        return {"content": [{"type": "text", "text": "Error: 'niche_id' and 'title' required."}]}
    if nid not in _niches:
        return {"content": [{"type": "text", "text": f"Niche '{nid}' not found."}]}
    tid = f"task_{_next_task_id}"
    _next_task_id += 1
    _tasks[tid] = {
        "id": tid, "niche_id": nid, "title": title,
        "desc": args.get("desc", ""), "priority": args.get("priority", "medium"),
        "status": "backlog", "column": _niches[nid]["columns"][0],
        "tags": args.get("tags", []), "assignee": args.get("assignee", ""),
        "references": {"chains": [], "patterns": [], "decisions": [], "wikis": []},
        "urls": [], "created_at": time.time(), "updated_at": time.time(),
    }
    _save_state()
    return {"content": [{"type": "text", "text": f"✅ Task created: {title} (ID: {tid}) in '{_niches[nid]['name']}'"}]}


def kanban_tool_task_move(args: dict) -> dict:
    from server import _tasks, _niches, _save_state
    tid = args.get("task_id", "")
    if tid not in _tasks:
        return {"content": [{"type": "text", "text": f"Task '{tid}' not found."}]}
    t = _tasks[tid]
    if "to_column" in args:
        col = args["to_column"]
        niche = _niches.get(t.get("niche_id", ""))
        if niche and col in niche.get("columns", []):
            t["column"] = col
    for k in ("title", "desc", "priority", "tags", "assignee"):
        if k in args and args[k] is not None:
            t[k] = args[k]
    t["updated_at"] = time.time()
    _save_state()
    return {"content": [{"type": "text", "text": f"✅ Task '{tid}' updated."}]}


def kanban_tool_task_list(args: dict) -> dict:
    from server import _tasks, _niches
    nid = args.get("niche_id")
    status = args.get("status")
    tag = args.get("tag")
    search = args.get("search", "").lower()
    limit = args.get("limit", 50)
    items = _tasks.values()
    if nid:
        items = [t for t in items if t.get("niche_id") == nid]
    if status:
        items = [t for t in items if t.get("status") == status]
    if tag:
        items = [t for t in items if tag in t.get("tags", [])]
    if search:
        items = [t for t in items if search in t.get("title", "").lower() or search in t.get("desc", "").lower()]
    items = sorted(items, key=lambda t: t.get("created_at", 0), reverse=True)[:limit]
    if not items:
        return {"content": [{"type": "text", "text": "No tasks found."}]}
    lines = [f"📋 Tasks ({len(items)} shown, {len(_tasks)} total):"]
    prio_icons = {"critical": "🔴", "high": "▲", "medium": "◇", "low": "▽"}
    col_icons = {"backlog": "📥", "in progress": "🔧", "review": "👁", "done": "✅", "blocked": "🚫"}
    for t in items:
        pi = prio_icons.get(t.get("priority", ""), "•")
        ci = col_icons.get(t.get("column", "").lower(), "📋")
        niche_name = _niches.get(t.get("niche_id", ""), {}).get("name", "?")
        refs = ""
        r = t.get("references", {})
        if r.get("chains"): refs += f" 🔗{len(r['chains'])}"
        if r.get("patterns"): refs += f" 🐞{len(r['patterns'])}"
        tag_str = f" [{', '.join(t.get('tags',[]))}]" if t.get("tags") else ""
        lines.append(f"  {pi} {ci} #{tid} [{niche_name}] {t.get('title','?')[:50]}{tag_str}{refs}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def kanban_tool_task_delete(args: dict) -> dict:
    from server import _tasks, _save_state
    tid = args.get("task_id", "")
    if tid not in _tasks:
        return {"content": [{"type": "text", "text": f"Task '{tid}' not found."}]}
    del _tasks[tid]
    _save_state()
    return {"content": [{"type": "text", "text": f"🗑️ Task '{tid}' deleted."}]}


def kanban_tool_task_search(args: dict) -> dict:
    from server import _tasks, _niches
    query = args.get("query", "").lower()
    nid = args.get("niche_id")
    status = args.get("status")
    priority = args.get("priority")
    tag = args.get("tag")
    limit = args.get("limit", 20)
    items = _tasks.values()
    if nid: items = [t for t in items if t.get("niche_id") == nid]
    if status: items = [t for t in items if t.get("status") == status]
    if priority: items = [t for t in items if t.get("priority") == priority]
    if tag: items = [t for t in items if tag in t.get("tags", [])]
    if query: items = [t for t in items if
        query in t.get("title", "").lower() or query in t.get("desc", "").lower() or
        query in str(t.get("references", {}))]
    items = sorted(items, key=lambda t: t.get("created_at", 0), reverse=True)[:limit]
    if not items:
        return {"content": [{"type": "text", "text": f"No tasks matching '{query}'."}]}
    prio_map = {"critical": "🔴", "high": "▲", "medium": "◇", "low": "▽"}
    lines = [f"🔍 Search results ({len(items)} found):"]
    for t in items:
        pi = prio_map.get(t.get("priority", ""), "•")
        nname = _niches.get(t.get("niche_id", ""), {}).get("name", "?")
        lines.append(f"  {pi} #{tid} [{nname}] {t.get('title','?')[:50]}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def kanban_tool_task_link(args: dict) -> dict:
    from server import _tasks, _save_state
    tid = args.get("task_id", "")
    if tid not in _tasks:
        return {"content": [{"type": "text", "text": f"Task '{tid}' not found."}]}
    t = _tasks[tid]
    refs = t.setdefault("references", {"chains": [], "patterns": [], "decisions": [], "wikis": []})
    for k in ("chain_id", "pattern_id", "decision_id", "wiki_id"):
        v = args.get(k)
        if v and k.replace("_id", "") + "s" in refs and v not in refs[k.replace("_id", "") + "s"]:
            refs[k.replace("_id", "") + "s"].append(v)
    _save_state()
    return {"content": [{"type": "text", "text": f"✅ Task linked to cognitive objects."}]}


def kanban_tool_task_link_url(args: dict) -> dict:
    from server import _tasks, _save_state
    tid = args.get("task_id", "")
    url = args.get("url", "")
    if tid not in _tasks:
        return {"content": [{"type": "text", "text": f"Task '{tid}' not found."}]}
    urls = _tasks[tid].setdefault("urls", [])
    if url not in urls:
        urls.append(url)
    _save_state()
    return {"content": [{"type": "text", "text": f"✅ URL linked to task '{tid}'."}]}


def kanban_tool_kanban_stats(args: dict) -> dict:
    from server import _tasks, _niches
    nid = args.get("niche_id")
    items = _tasks.values()
    if nid: items = [t for t in items if t.get("niche_id") == nid]
    total = len(items)
    by_column = {}
    by_priority = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for t in items:
        col = t.get("column", "backlog").lower()
        by_column[col] = by_column.get(col, 0) + 1
        prio = t.get("priority", "medium")
        if prio in by_priority: by_priority[prio] += 1
    lines = [f"📊 Kanban Stats{' for ' + str(nid) if nid else ''}:",
             f"  Total tasks: {total}"]
    if by_column:
        lines.append(f"  By column: {', '.join(f'{k}: {v}' for k, v in sorted(by_column.items()))}")
    if by_priority:
        lines.append(f"  By priority: {', '.join(f'{k}: {v}' for k, v in sorted(by_priority.items()) if v > 0)}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


# ═══════════════════════════════════════════════════════════════════════
# Exports for server.py
# ═══════════════════════════════════════════════════════════════════════

KANBAN_HANDLERS = {
    "niche_create": kanban_tool_niche_create,
    "niche_list": kanban_tool_niche_list,
    "niche_update": kanban_tool_niche_update,
    "task_create": kanban_tool_task_create,
    "task_move": kanban_tool_task_move,
    "task_list": kanban_tool_task_list,
    "task_delete": kanban_tool_task_delete,
    "task_search": kanban_tool_task_search,
    "task_link": kanban_tool_task_link,
    "task_link_url": kanban_tool_task_link_url,
    "kanban_stats": kanban_tool_kanban_stats,
}

KANBAN_SCHEMAS = [
    {
        "name": "niche_create",
        "description": "Create a new cognitive niche (project/area). [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Niche name"},
                "desc": {"type": "string", "description": "Niche description"},
                "color": {"type": "string", "description": "Niche color (hex)", "default": "#22d3ee"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "niche_list",
        "description": "List all cognitive niches. [LUMEN SHM]",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "niche_update",
        "description": "Update niche properties (name, desc, color, columns, archive). [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "niche_id": {"type": "string", "description": "Niche ID"},
                "name": {"type": "string", "description": "New name"},
                "color": {"type": "string", "description": "New color (hex)"},
                "archived": {"type": "boolean", "description": "Archive (true) or unarchive (false)"}
            },
            "required": ["niche_id"]
        }
    },
    {
        "name": "task_create",
        "description": "Create a new task in a niche. [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "niche_id": {"type": "string", "description": "Niche ID"},
                "title": {"type": "string", "description": "Task title"},
                "desc": {"type": "string", "description": "Task description"},
                "priority": {"type": "string", "description": "Task priority", "default": "medium"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Task tags"}
            },
            "required": ["niche_id", "title"]
        }
    },
    {
        "name": "task_move",
        "description": "Move a task to a column (or edit fields). [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
                "to_column": {"type": "string", "description": "Target column (e.g., Backlog, In Progress, Done)"},
                "title": {"type": "string", "description": "New title"},
                "priority": {"type": "string", "description": "New priority"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "task_list",
        "description": "List tasks with optional filtering. [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "niche_id": {"type": "string", "description": "Filter by niche ID"},
                "status": {"type": "string", "description": "Filter by status"},
                "tag": {"type": "string", "description": "Filter by tag"},
                "search": {"type": "string", "description": "Search in title/desc"},
                "limit": {"type": "integer", "description": "Max results"}
            }
        }
    },
    {
        "name": "task_delete",
        "description": "Delete a task permanently. [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID to delete"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "task_search",
        "description": "Search tasks across niches by title, description, tags, references. [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search text"},
                "niche_id": {"type": "string", "description": "Filter by niche ID"},
                "status": {"type": "string", "description": "Filter by status"},
                "priority": {"type": "string", "description": "Filter by priority"},
                "tag": {"type": "string", "description": "Filter by tag"},
                "limit": {"type": "integer", "description": "Max results"}
            }
        }
    },
    {
        "name": "task_link",
        "description": "Link a task to LUMEN cognitive objects (chain, pattern, decision, wiki). [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
                "chain_id": {"type": "string", "description": "Chain ID to link"},
                "pattern_id": {"type": "string", "description": "Pattern ID to link"},
                "decision_id": {"type": "string", "description": "Decision ID to link"},
                "wiki_id": {"type": "string", "description": "Wiki ID to link"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "task_link_url",
        "description": "Link URL to a kanban task. [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "url": {"type": "string"}
            },
            "required": ["task_id", "url"]
        }
    },
    {
        "name": "kanban_stats",
        "description": "Show kanban statistics per niche. [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "niche_id": {"type": "string", "description": "Filter by niche ID (optional)"}
            }
        }
    },
]
