#!/usr/bin/env python3
"""test_ecosistema.py — Suite de tests de regresión del ecosistema Cadences Lab.

Cubre: vm-api (health, bitácora, espectro), MVM de Poli (exec, rutina LQ),
puente Lumen Quantum (emulador), sitio libros.cadenceslab.com (índice, capítulos, audio),
token del dashboard. Ejecutar ANTES y DESPUÉS de cambios para no romper nada.

Uso:  python tests/test_ecosistema.py  (exit 0 = todo verde)
"""
import json
import os
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8081"
POLI = "http://127.0.0.1:8082"
SITE = "https://libros.cadenceslab.com"
TOKEN = ""
try:
    TOKEN = open(os.path.expanduser("~/.hermes/dashboard.token"), encoding="utf-8").read().strip()
except Exception:
    TOKEN = ""

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail and not ok else ""))


def http_json(url, timeout=30):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"success": False, "error": f"http {e.code}"}


def http_json_post(url, payload, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def auth(url):
    return url + (("&" if "?" in url else "?") + f"t={TOKEN}") if TOKEN else url


def http_status(url, timeout=60):
    req = urllib.request.Request(url, method="HEAD" if url.endswith(".mp3") else "GET",
                                 headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


print("=== 1. vm-api ===")
try:
    h = http_json(f"{BASE}/ddp/health", 10)
    check("health", h.get("ok") or h.get("success") or "healthy" in str(h), str(h)[:60])
except Exception as e:
    check("health", False, str(e)[:80])

print("=== 2. Bitácora Inmutable ===")
try:
    v = http_json(auth(f"{BASE}/ddp/bitacora/verify"), 15)
    b = v.get("bitacora", {})
    check("cadena íntegra", b.get("ok") is True, f"broken={b.get('broken')}")
    check("eventos ≥ 7", b.get("entries", 0) >= 7, f"entries={b.get('entries')}")
except Exception as e:
    check("cadena íntegra", False, str(e)[:80])
    check("eventos ≥ 7", False, "")

print("=== 3. El Espectro (nuevo) ===")
try:
    e = http_json(auth(f"{BASE}/ddp/espectro"), 15).get("espectro", {})
    check("espectro ok", e.get("ok") is True)
    check("agentes reconstruidos", len(e.get("agentes", {})) >= 3, f"agentes={list(e.get('agentes', {}))}")
    check("snapshot versionado", e.get("snapshot", {}).get("version", 0) >= 7, f"v={e.get('snapshot', {}).get('version')}")
    r = http_json(auth(f"{BASE}/ddp/espectro?hasta_seq=4"), 15).get("espectro", {})
    check("rollback hasta_seq=4", r.get("eventos") == 4, f"eventos={r.get('eventos')}")
except Exception as ex:
    check("espectro ok", False, str(ex)[:80])
    check("agentes reconstruidos", False, "")
    check("snapshot versionado", False, "")
    check("rollback hasta_seq=4", False, "")

print("=== 4. MVM de Poli ===")
try:
    d = http_json_post(f"{POLI}/v1/exec", {"code": "W \"vivo\"", "gas_limit": 5000}, 30)
    check("exec responde", d.get("ok") is True, str(d)[:80])
    d2 = http_json_post(f"{POLI}/v1/exec", {"code": 'W $$LQBACKENDS^LQ()', "gas_limit": 10000}, 30)
    check("rutina LQ cargada", "Tuna" in d2.get("output", ""), d2.get("output", "")[:80])
except Exception as e:
    check("exec responde", False, str(e)[:80])
    check("rutina LQ cargada", False, "")

print("=== 5. Puente Lumen Quantum (emulador) ===")
try:
    code = 'W $$LQ^LQ("bell","1",512)'
    req = urllib.request.Request(f"{POLI}/v1/exec",
                                 data=json.dumps({"code": code, "gas_limit": 60000}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
    out = d.get("output", "")
    job = ""
    try:
        job = json.loads(out).get("job_id", "")
    except Exception:
        pass
    check("LQ^LQ lanza job", bool(job), out[:80])
    if job:
        time.sleep(5)
        code2 = f'W $$LQR^LQ("{job}")'
        req2 = urllib.request.Request(f"{POLI}/v1/exec",
                                      data=json.dumps({"code": code2, "gas_limit": 60000}).encode(),
                                      headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req2, timeout=60) as r:
            d2 = json.loads(r.read())
        out2 = d2.get("output", "")
        check("LQR^LQ devuelve counts", '"counts"' in out2 or "done" in out2, out2[:80])
except Exception as e:
    check("LQ^LQ lanza job", False, str(e)[:100])
    check("LQR^LQ devuelve counts", False, "")

print("=== 6. Sitio libros.cadenceslab.com ===")
try:
    check("index 200", http_status(f"{SITE}/") == 200)
    check("índice El Prisma 200", http_status(f"{SITE}/libro/v10-el-prisma/") == 200)
    check("cap 30 200", http_status(f"{SITE}/libro/v10-el-prisma/30-cierre-los-agentes-nacen/") == 200)
    check("cap 32 200", http_status(f"{SITE}/libro/v10-el-prisma/32-plan-zzz/") == 200)
    check("audio cap 32 200", http_status(f"{SITE}/audio/v10-el-prisma/32-plan-zzz.mp3", 90) == 200)
except Exception as e:
    check("sitio accesible", False, str(e)[:80])

print("=== 7. Dashboard token ===")
try:
    st = http_status(f"{BASE}/web/dashboard?t={TOKEN}") if TOKEN else 0
    check("dashboard con token 200", st == 200, f"status={st}")
    st2 = http_status(f"{BASE}/web/dashboard") if TOKEN else 0
    check("dashboard sin token bloqueado", st2 in (301, 302, 401, 403), f"status={st2}")
except Exception as e:
    check("dashboard token", False, str(e)[:80])

print("=== 8. El Salón (Poli lee/escribe) ===")
try:
    r = http_json(auth(f"{BASE}/ddp/salon/read?path=README.md"), 15)
    check("salon read README", r.get("success") is True and "El Salón" in r.get("content", ""))
    s = http_json_post(auth(f"{BASE}/ddp/salon/write"),
                       {"path": "partes/test-suite.md", "content": "test de la suite"}, 15)
    check("salon write", s.get("success") is True and "partes/test-suite.md" in s.get("path", ""))
    r2 = http_json(auth(f"{BASE}/ddp/salon/read?path=partes/test-suite.md"), 15)
    check("salon read vuelta", r2.get("content", "").strip() == "test de la suite")
    b = http_json(auth(f"{BASE}/ddp/salon/read?path=../secret.md"), 15)
    check("traversal bloqueado", b.get("success") is False)
except Exception as e:
    check("salon", False, str(e)[:80])
    check("salon read vuelta", False, "")
    check("traversal bloqueado", False, "")

print("=== 9. Heartbeat del ecosistema ===")
try:
    hb = http_json_post(f"{POLI}/v1/exec", {"code": 'W $G(^ANGI(metrics,agents_online_mvm))', "gas_limit": 20000}, 15)
    vivos = (hb.get("output") or "").strip()
    check("mvm agents_online_mvm > 0", vivos.isdigit() and int(vivos) > 0, f"vivos={vivos}")
    hb2 = http_json_post(f"{POLI}/v1/exec", {"code": 'S k="" F S k=$O(^HEARTBEAT(k)) Q:k="" W k," "', "gas_limit": 20000}, 15)
    check("mvm heartbeats presentes", "hermes" in (hb2.get("output") or ""), "sin heartbeats")
except Exception as e:
    check("mvm heartbeat", False, str(e)[:80])
    check("mvm heartbeats presentes", False, "")

print("=== 10. Los Pesos del Tiempo (decay + coherencia binaria) ===")
try:
    import sqlite3 as _sq
    _db = os.environ.get("PDB_PATH", r"C:\Users\gonzalo\pdb-data\lumen-pdb.db")
    # 10.1 sembrar desde el MVM (formato binario M) → el fichero lo ve en binario
    s1 = http_json_post(f"{POLI}/v1/exec", {"code": 'S ^WEIGHTS(TESTA)="7|2|2026-08-10T00:00:00Z" S ^WEIGHTS(TESTB)="0.05|1|2026-07-01T00:00:00Z"', "gas_limit": 20000}, 15)
    _c = _sq.connect(_db)
    _a = _c.execute("SELECT value FROM _globals WHERE ns='WEIGHTS' AND subkey=?", (b"\x02TESTA\xff",)).fetchone()
    _b = _c.execute("SELECT value FROM _globals WHERE ns='WEIGHTS' AND subkey=?", (b"\x02TESTB\xff",)).fetchone()
    _c.close()
    check("pesos siembra M→fichero binario", _a is not None and _b is not None, f"a={_a} b={_b}")
    # 10.2 coherencia: el fichero y el MVM ven el MISMO nodo
    _vm = http_json_post(f"{POLI}/v1/exec", {"code": 'W $G(^WEIGHTS(TESTA))', "gas_limit": 20000}, 15)
    check("pesos coherencia fichero==MVM", _a and (_a[0] == (_vm.get("output") or "").strip()), f"f={_a[0] if _a else '?'} m={_vm.get('output','')}")
    # 10.3 decay: PESOSDECAY(0.5, 0.1) → TESTA decae a 3.5, TESTB se purga, meta se escribe
    _d = http_json_post(f"{POLI}/v1/exec", {"code": 'W $$PESOSDECAY^PESOSDECAY(0.5,0.1,"2026-08-17T06:00:00Z")', "gas_limit": 40000}, 15)
    _c = _sq.connect(_db)
    _a2 = _c.execute("SELECT value FROM _globals WHERE ns='WEIGHTS' AND subkey=?", (b"\x02TESTA\xff",)).fetchone()
    _b2 = _c.execute("SELECT value FROM _globals WHERE ns='WEIGHTS' AND subkey=?", (b"\x02TESTB\xff",)).fetchone()
    _m = _c.execute("SELECT value FROM _globals WHERE ns='WEIGHTSMETA'").fetchone()
    _c.close()
    check("pesos decay aplicado (7→3.5)", _a2 is not None and _a2[0].startswith("3.5|"), f"v={_a2[0] if _a2 else '?'}")
    check("pesos purga obsoletos", _b2 is None, f"v={_b2[0] if _b2 else 'purgado'}")
    check("pesos meta escrito", _m is not None and "|" in _m[0], f"meta={_m[0] if _m else '?'}")
    # limpieza
    _c = _sq.connect(_db)
    _c.execute("DELETE FROM _globals WHERE ns='WEIGHTS' AND subkey IN (?,?)", (b"\x02TESTA\xff", b"\x02TESTB\xff"))
    _c.commit(); _c.close()
except Exception as e:
    check("pesos", False, str(e)[:100])
    check("pesos coherencia", False, "")
    check("pesos decay", False, "")
    check("pesos purga", False, "")
    check("pesos meta", False, "")

print(f"\n{'='*50}\nRESULTADO: {len(PASS)} ✅  |  {len(FAIL)} ❌")
if FAIL:
    print("FALLOS:", " | ".join(FAIL))
    sys.exit(1)
print("TODO VERDE — el ecosistema sigue sano. 🌱")
