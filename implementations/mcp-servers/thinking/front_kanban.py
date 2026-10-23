"""Puente de escritura del kanban del thinking server hacia cadences.app.

La app es la VERDAD visible; la PDB queda como espejo local.
Sin secretos en el repo: la configuracion se lee de
  ~/AppData/Local/hermes/cadences_agent.json  (fuera de git)
o de las variables CADENCES_CUSTOMER_ID / CADENCES_ORG_ID / CADENCES_AGENT_ID.

Reglas (ADR-002 v1.1):
  - errores RUIDOSOS: nunca devolver exito si la app fallo
  - idempotencia: tag 'ext:<id_local>' (el id de la PDB) para no duplicar
"""
import json, os, time, urllib.request, urllib.error, uuid

_CFG_CACHE = None


def _cfg():
    global _CFG_CACHE
    if _CFG_CACHE is not None:
        return _CFG_CACHE
    cfg = {}
    if os.environ.get("CADENCES_CUSTOMER_ID"):
        cfg = {
            "customer_id": os.environ["CADENCES_CUSTOMER_ID"],
            "organization_id": os.environ.get("CADENCES_ORG_ID", ""),
            "agent_id": os.environ.get("CADENCES_AGENT_ID", "hermes"),
            "api_base": os.environ.get("CADENCES_API", "https://cadences.app/api"),
            "default_project_id": os.environ.get("CADENCES_DEFAULT_PROJECT", ""),
            "project_map": {},
        }
    else:
        path = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")),
                            "hermes", "cadences_agent.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
    _CFG_CACHE = cfg
    return cfg


ESTADOS = {"backlog": "Por Hacer", "in progress": "En Progreso", "in_progress": "En Progreso",
           "review": "En Progreso", "blocked": "Por Hacer", "done": "Completado",
           "completado": "Completado", "por hacer": "Por Hacer", "en progreso": "En Progreso"}
PRIOS = {"critical": "High", "high": "High", "medium": "Medium", "low": "Low"}


def estado_de(columna):
    return ESTADOS.get(str(columna or "").strip().lower(), "Por Hacer")


def prioridad_de(p):
    return PRIOS.get(str(p or "medium").strip().lower(), "Medium")


def proyecto_de(niche_id):
    cfg = _cfg()
    return (cfg.get("project_map") or {}).get(niche_id) or cfg.get("default_project_id") or ""


def _token():
    """Token del agente desde ~/AppData/Local/hermes/agent_tokens.json (fuera de git)."""
    path = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")),
                        "hermes", "agent_tokens.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get(_cfg().get("agent_id", "hermes"), "")
    except Exception:
        return ""


def _req(method, path, body=None, idem=None):
    cfg = _cfg()
    if not cfg.get("customer_id"):
        raise RuntimeError("cadences.app no configurado (falta cadences_agent.json o CADENCES_CUSTOMER_ID)")
    h = {"X-Customer-ID": cfg["customer_id"], "X-Agent-Id": cfg.get("agent_id", "hermes"),
         "User-Agent": "lumen-thinking/1.0"}
    tok = _token()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    if cfg.get("organization_id"):
        h["X-Organization-ID"] = cfg["organization_id"]
    data = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode()
        h["Content-Type"] = "application/json"
    if idem:
        h["Idempotency-Key"] = idem
    req = urllib.request.Request(cfg["api_base"].rstrip("/") + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
    except Exception as e:
        raise RuntimeError(f"{type(e).__name__}: {e}")


INV_ESTADO = {"por hacer": "Backlog", "en progreso": "In Progress",
              "completado": "Done", "cancelada": "Cancelled"}
INV_PRIO = {"high": "high", "medium": "medium", "low": "low"}


def listar_tareas(niche_id):
    """Lee las tareas del proyecto mapeado en cadences.app.

    Devuelve None si el nicho no tiene proyecto (-> el llamante usa la PDB).
    """
    pid = proyecto_de(niche_id)
    if not pid:
        return None
    d = _req("GET", "/tasks?projectId=%s&limit=500" % pid)
    filas = d.get("tasks") or d.get("data") or []
    ahora = time.time()
    out = []
    for i, t in enumerate(filas):
        tags = t.get("tags")
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []
        tags = tags or []
        ext = next((str(x)[4:] for x in tags if str(x).startswith(("ext:", "pdb:"))), t.get("id"))
        out.append({
            "id": ext,
            "front_id": t.get("id"),
            "niche_id": niche_id,
            "title": t.get("title") or "",
            "desc": t.get("description") or "",
            "column": INV_ESTADO.get(str(t.get("status") or "").lower(), t.get("status") or "Backlog"),
            "priority": INV_PRIO.get(str(t.get("priority") or "").lower(), "medium"),
            "tags": [x for x in tags if not str(x).startswith(("ext:", "agent:", "pdb-niche:", "pdb:"))],
            "assignee": t.get("assignedTo") or "",
            "references": {},
            "created_at": ahora - i,
            "updated_at": ahora - i,
        })
    return out


def crear_tarea(task_local: dict) -> str:
    """Crea la tarea en la app. Devuelve el id del front."""
    pid = proyecto_de(task_local.get("niche_id", ""))
    if not pid:
        raise RuntimeError("sin proyecto destino (project_map/default_project_id vacio)")
    tid = f"task_{int(time.time()*1000)}_{uuid.uuid4().hex[:9]}"
    ahora = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    tags = [f"agent:{_cfg().get('agent_id','hermes')}", f"pdb-niche:{task_local.get('niche_id','')}",
            f"ext:{task_local.get('id','')}"] + [str(t) for t in (task_local.get("tags") or [])]
    body = {"id": tid, "projectId": pid, "customerId": _cfg()["customer_id"],
            "assignedTo": f"user_{_cfg().get('agent_id','hermes')}",
            "title": (task_local.get("title") or "")[:250],
            "description": task_local.get("desc") or "",
            "status": estado_de(task_local.get("column")),
            "priority": prioridad_de(task_local.get("priority")),
            "tags": tags,
            "data": {"id": tid, "title": task_local.get("title"), "pdbId": task_local.get("id"),
                     "createdAt": ahora, "updatedAt": ahora, "isDeleted": False}}
    _req("POST", "/tasks", body, idem=f"task-{task_local.get('id','')}")
    return tid


def mover_tarea(front_id: str, columna: str, extra: dict = None):
    body = {"status": estado_de(columna)}
    if extra:
        if extra.get("title"):
            body["title"] = extra["title"][:250]
        if extra.get("desc") is not None:
            body["description"] = extra["desc"]
        if extra.get("priority"):
            body["priority"] = prioridad_de(extra["priority"])
    if not front_id:
        raise RuntimeError("la tarea local no tiene front_id (no se creo en la app)")
    return _req("PUT", f"/tasks/{front_id}", body)


def borrar_tarea(front_id: str):
    if not front_id:
        raise RuntimeError("la tarea local no tiene front_id")
    return _req("DELETE", f"/tasks/{front_id}")
