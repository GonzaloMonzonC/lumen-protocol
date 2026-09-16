#!/usr/bin/env python3
"""Regresion incidente 6 (16-sep-2026) — los contadores releen el max persistido.

Simula una instancia STALE: la memoria va por detras de la PDB (se siembran
task_900 y niche_50 SOLO en la PDB, DESPUES de cargar el estado en memoria).
Sin el fix, task_create/niche_create devolverian el id del contador viejo;
con el fix, releen el max persistido y asignan task_901 / niche_51.

Usa una COPIA temporal de la PDB — no toca la PDB real ni el .thinking_state.json
del dashboard. Uso: python test_kanban_counter_sync.py
"""
import os, sys, json, sqlite3, shutil, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
# Prioridad: el server.py DE ESTE DIRECTORIO gana. OJO: cada insert(0) adelanta,
# asi que el ultimo insert es el de mayor prioridad -> HERE va el ULTIMO.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "python", "src"))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

# 1) resolver la PDB fuente SIN importar el stack (pdb_tools CACHEA la ruta en
#    el primer _get_db_path(): si importas primero y rediriges despues, todo
#    (load Y save) va a la PDB REAL — incidente 16-sep-2026, ver cleanup).
SRC = (os.environ.get("LUMEN_TEST_SRC_PDB")
       or os.environ.get("PDB_PATH")
       or r"C:/Users/gonzalo/pdb-data/lumen-pdb.db")

# 2) copia temporal CONSISTENTE — backup API (incluye el WAL; shutil.copyfile
#    NO lo copia y la copia sale VIEJA — detectado 16-sep-2026: el test veia
#    el niche_6 ya borrado y fallaba en falso)
tmpdir = tempfile.mkdtemp(prefix="lumen_kb_sync_")
dst = os.path.join(tmpdir, "lumen-pdb-test.db")
_s = sqlite3.connect(SRC)
_d = sqlite3.connect(dst)
_s.backup(_d)
_d.close()
_s.close()
print(f"[test] PDB fuente: {SRC}")
print(f"[test] copia:      {dst}")

# 3) REDIRIGIR ANTES de importar el stack + cinturon sobre la cache de pdb_tools
os.environ["PDB_PATH"] = dst
import _pdb
import pdb_tools
pdb_tools._DB_PATH = dst   # la cache ya no puede apuntar a la real
_pdb.PDB_PATH = dst

# guardia fail-fast: PRAGMA confirma que las conexiones van a la copia
_c = pdb_tools.pdb_connect(readonly=True)
_r0 = _c.execute("PRAGMA database_list").fetchall()[0]
_c.close()
_dbp = _r0["file"] if isinstance(_r0, sqlite3.Row) else _r0[2]
assert os.path.normcase(os.path.normpath(str(_dbp))) == os.path.normcase(os.path.normpath(dst)), \
    f"PDB mal redirigida: {_dbp} — ABORT (no se toca nada)"
print(f"[test] redireccion OK: {_dbp}")

import server
# Blindaje: verificar que 'server' es ESTE server.py (no otro con nombre igual)
if os.path.dirname(os.path.abspath(server.__file__)) != HERE:
    import importlib.util
    print(f"[test] aviso: 'server' resolvio a {server.__file__} -> fuerzo el local")
    spec = importlib.util.spec_from_file_location("server", os.path.join(HERE, "server.py"))
    server = importlib.util.module_from_spec(spec)
    sys.modules["server"] = server
    spec.loader.exec_module(server)
assert hasattr(server, "_load_state"), f"server sin _load_state: {server.__file__}"
server._load_state()
server._JSON_SNAPSHOT_INTERVAL = 0  # no tocar el snapshot JSON real
try:
    server._STATE_FILE = os.path.join(tmpdir, ".thinking_state.json")
except Exception:
    pass


def seed(state_key, payload):
    con = sqlite3.connect(dst)
    con.execute("INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?,?,?)",
                ("STATE", state_key, json.dumps(payload)))
    con.commit()
    con.close()


# 4) sembrar ids ALTOS solo en la PDB (la memoria ya cargo -> no los conoce)
seed("global:task:task_900", {"id": "task_900", "niche_id": "niche_1", "title": "seed stale",
     "desc": "sembrado solo en PDB", "priority": "low", "status": "backlog", "column": "Backlog",
     "tags": [], "assignee": "",
     "references": {"chains": [], "patterns": [], "decisions": [], "wikis": []},
     "urls": [], "created_at": 0, "updated_at": 0})
seed("global:niche:niche_50", {"id": "niche_50", "name": "SeedNiche", "color": "#000000",
     "desc": "", "columns": ["Backlog"], "archived": False, "created_at": 0})

# asertos de visibilidad: el sync debe VER los seeds antes de nada
mx_t = server._max_persisted_id("task")
mx_n = server._max_persisted_id("niche")
print(f"[test] sync ve: max task={mx_t} (espera 900) · max niche={mx_n} (espera 50)")
assert mx_t == 900, f"seed task_900 no visible para el sync: {mx_t}"
assert mx_n == 50, f"seed niche_50 no visible para el sync: {mx_n}"

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  OK  {name}")
    else:
        failed += 1
        print(f"  FAIL {name} :: {detail}")


# 5) create con el fix: debe releer max persistido (900/50) -> 901 / 51
r = server.HANDLERS["task_create"]({"niche_id": "niche_1", "title": "TEST sync contador",
    "desc": "regresion incidente 6", "priority": "low", "tags": ["test"]})
t = r["content"][0]["text"]
check("task_create relee max persistido (espera task_901)", "task_901" in t, t)

r2 = server.HANDLERS["niche_create"]({"name": "TEST sync niche", "color": "#000000", "desc": ""})
t2 = r2["content"][0]["text"]
check("niche_create relee max persistido (espera niche_51)", "niche_51" in t2, t2)

# 6) control negativo: sin el sync (monkeypatch no-op) vuelve al contador viejo
time.sleep(1.5)  # deja terminar el save async de la fase anterior
server._sync_counter_from_pdb = lambda kind: None
server._next_task_id = 178
r3 = server.HANDLERS["task_create"]({"niche_id": "niche_1", "title": "TEST control negativo",
    "desc": "sin sync", "priority": "low", "tags": ["test"]})
t3 = r3["content"][0]["text"]
check("control: sin sync asignaria el id viejo (task_178) -> el test discrimina",
      "task_178" in t3, t3)

print(f"\n{'TODO VERDE' if failed == 0 else 'HAY FALLOS'} — {passed} ok, {failed} fail")
print(f"[test] tmp: {tmpdir}")
sys.exit(1 if failed else 0)
