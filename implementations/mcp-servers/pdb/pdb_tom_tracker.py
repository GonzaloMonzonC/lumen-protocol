"""Tom Task Tracker — Log de tareas de Tom en PDB.

Tom es un Cloudflare Worker (sin estado local). Este tracker
mantiene un registro persistente de todas las tareas que le
enviamos, sus resultados y estado.

USO:
  from pdb_tom_tracker import *
  task_id = tom_track_start('classify', {'text': '...', 'categories': [...]})
  # ... llamar a Tom ...
  tom_track_complete(task_id, result)
  # Angi consulta:
  tasks = tom_list_active()
"""
import json, time, os, sys

sys.path.insert(0, os.path.dirname(__file__) or '.')
import pdb_tools

NS = "TOM"

def _ts():
    return time.strftime("%Y-%m-%dT%H:%M:%S")

def _next_id():
    """Next task ID using reverse $ORDER."""
    r = pdb_tools.tool_order({"ns": NS, "subs": ["tasks", ""], "direction": -1})
    if r is None:
        return 1
    v = r.get("value") if isinstance(r, dict) else r
    if v is None or v == "":
        return 1
    return int(float(v)) + 1

def tom_track_start(operation, params, source="hermes"):
    """Registra el inicio de una tarea de Tom. Devuelve task_id."""
    tid = _next_id()
    data = {
        "id": tid,
        "operation": operation,
        "params": params,
        "source": source,
        "status": "running",
        "started": _ts(),
        "completed": None,
        "result": None,
        "error": None
    }
    pdb_tools.tool_set({"ns": NS, "subs": ["tasks", tid], "value": json.dumps(data)})
    return tid

def tom_track_complete(task_id, result=None, error=None):
    """Marca tarea como completada o fallida."""
    d = tom_get_task(task_id)
    if not d:
        return False
    if error:
        d["status"] = "failed"
        d["error"] = str(error)
    else:
        d["status"] = "completed" if result is not None else "running"
        d["result"] = result
    d["completed"] = _ts()
    pdb_tools.tool_set({"ns": NS, "subs": ["tasks", task_id], "value": json.dumps(d)})
    return True

def tom_get_task(task_id):
    """Lee una tarea por ID."""
    r = pdb_tools.tool_get({"ns": NS, "subs": ["tasks", task_id]})
    if not r or not r.get("success") or r.get("value") is None:
        return None
    try: return json.loads(r["value"])
    except: return {"id": task_id, "raw": r["value"]}

def tom_list_tasks(status=None, limit=20):
    """Lista tareas opcionalmente filtradas por status.
    status: 'running', 'completed', 'failed', None (todas)"""
    tasks = []
    key = ""
    while True:
        r = pdb_tools.tool_order({"ns": NS, "subs": ["tasks", key]})
        if r is None: break
        nk = r.get("value") if isinstance(r, dict) else r
        if nk is None or nk == "" or nk == key: break
        key = nk
        d = tom_get_task(key)
        if d and (not status or d.get("status") == status):
            tasks.append(d)
            if len(tasks) >= limit:
                break
    return tasks

def tom_list_active():
    """Tareas en ejecución (running)."""
    return tom_list_tasks(status="running")

def tom_list_recent(limit=10):
    """Últimas N tareas (ordenadas por id descendente)."""
    tasks = tom_list_tasks(limit=limit*3)  # fetch more, filter later
    # Sort by id descending
    tasks.sort(key=lambda t: -(t.get("id", 0)))
    return tasks[:limit]

def tom_status():
    """Resumen del tracker."""
    active = tom_list_active()
    all_t = tom_list_tasks(limit=100)
    completed = [t for t in all_t if t.get("status") == "completed"]
    failed = [t for t in all_t if t.get("status") == "failed"]
    return {
        "active": len(active),
        "completed": len(completed),
        "failed": len(failed),
        "total": len(all_t),
        "recent": tom_list_recent(5)
    }

# ── Wrappers para llamadas a Tom ──
# Estas funciones llaman a Tom VIA MCP y trackean automáticamente.
# Se usan desde Hermes cuando delegamos a Tom.

def tom_process(prompt, tier="FLASH"):
    """Wrapper: llama a tom_process + trackea."""
    tid = tom_track_start("process", {"prompt": prompt[:100], "tier": tier})
    try:
        # La llamada real a Tom
        from hermes_tools import call_mcp
        result = call_mcp("tom", "mcp_tom_tom_process", {"prompt": prompt, "tier": tier})
        # Also could use mcp_tom_tom_process directly when available
        tom_track_complete(tid, result=result)
        return result
    except Exception as e:
        tom_track_complete(tid, error=str(e))
        raise

if __name__ == "__main__":
    import json
    s = tom_status()
    print(json.dumps(s, indent=2))
