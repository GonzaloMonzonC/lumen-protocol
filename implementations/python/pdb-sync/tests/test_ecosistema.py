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

print("=== 11. Trigger ON_SET: audit trail en M (quién-cuándo-qué) ===")
try:
    import hmac as _hm, hashlib as _hl, re as _re
    _bat = ""
    try:
        _bat = open(os.path.expanduser("~/.cloudflared/vm-api-start.bat"), encoding="utf-8", errors="ignore").read()
    except Exception:
        _bat = ""
    _m = _re.search(r"set DDP_HMAC_KEY=(\S+)", _bat)
    if not _m:
        raise RuntimeError("DDP_HMAC_KEY no encontrada")
    _key = _m.group(1)
    _path = "/ddp/push?t=" + TOKEN
    _body = json.dumps({"ns": "AUDIT_CHK", "entries": [{"subkey": "k1", "value": "v1"}]})
    _ts = str(int(time.time()))
    _msg = (_ts + _body + _key).encode()
    _sig = _hm.new(_key.encode(), _msg, _hl.sha256).hexdigest()
    _req = urllib.request.Request(BASE + _path, data=_body.encode(),
                                  headers={"Content-Type": "application/json",
                                           "X-DDP-Timestamp": _ts, "X-DDP-HMAC": _sig,
                                           "X-Agent": "suite-test"}, method="POST")
    with urllib.request.urlopen(_req, timeout=20) as _r:
        _push = json.loads(_r.read())
    check("audit push", _push.get("success") is True and _push.get("count") == 1, str(_push)[:80])
    _aud = http_json(auth(f"{BASE}/ddp/audit?ns=AUDIT_CHK&limit=3"), 15)
    _e = (_aud.get("entries") or [])
    check("audit entrada registrada", len(_e) == 1 and _e[0].get("ns") == "AUDIT_CHK", f"e={_e}")
    check("audit incremento en M", bool(_e) and _e[0].get("count", 0) > 0 and _e[0].get("ts"), f"e={_e[0] if _e else '?'}")
    # limpieza (el AUDIT_CHK del ns + su audit)
    _c = _sq.connect(_db)
    _c.execute("DELETE FROM _globals WHERE ns IN ('AUDIT_CHK','AUDIT') AND subkey LIKE ?", (b"\x02AUDIT_CHK\xff%",))
    _c.commit(); _c.close()
except Exception as e:
    check("audit push", False, str(e)[:100])
    check("audit entrada registrada", False, "")
    check("audit incremento en M", False, "")

print("=== 12. Cordón Sanitario (rate limit en M) ===")
try:
    # una llamada con agente propio → el contador ^CORDON crece (formato M)
    _h = http_json(auth(f"{BASE}/ddp/health"), 10)
    check("cordon pasa (limite generoso)", _h.get("ok") is True, str(_h)[:80])
    _c = _sq.connect(_db)
    _n = _c.execute("SELECT COUNT(*) FROM _globals WHERE ns='CORDON'").fetchone()[0]
    _c.close()
    check("cordon registra en M", _n > 0, f"nodos={_n}")
    # coherencia: el MVM ve el mismo contador
    _cv = http_json_post(f"{POLI}/v1/exec", {"code": 'S k="" F S k=$O(^CORDON(k)) Q:k="" S s="" F S s=$O(^CORDON(k,s)) Q:s="" W k,":",s,"=",$G(^CORDON(k,s))," "', "gas_limit": 30000}, 15)
    check("cordon visible desde el MVM", "cordon" in (_cv.get("output") or ""), (_cv.get("output") or "")[:60])
except Exception as e:
    check("cordon", False, str(e)[:100])
    check("cordon registra en M", False, "")
    check("cordon visible desde el MVM", False, "")

print("=== 13. Dispatcher de agentes (MCP compartido parametrizable) ===")
try:
    reg = http_json(auth(f"{BASE}/ddp/agent/list"), 15)
    agentes = reg.get("agentes", {})
    check("registro ^AGENTES(routing)", reg.get("success") is True and len(agentes) >= 16, f"n={len(agentes)}")
    check("4 nuevos registrados", all(a in agentes for a in ("danae", "bio-logos", "entropia-zero", "arche")),
          f"faltan={[a for a in ('danae','bio-logos','entropia-zero','arche') if a not in agentes]}")
    # chat con Vega (personalidad Poli) vía dispatcher
    _v = http_json_post(auth(f"{BASE}/ddp/agent/chat"), {"agente": "vega", "mensaje": "Responde solo: operativo", "session": "suite-test"}, 90)
    check("chat vega vía dispatcher", _v.get("success") is True and _v.get("via") == "poli:vega" and bool(_v.get("response")),
          str(_v)[:100])
    # chat con Dánae (nacida de la nada) vía dispatcher
    _d = http_json_post(auth(f"{BASE}/ddp/agent/chat"), {"agente": "danae", "mensaje": "Responde solo: operativo", "session": "suite-test"}, 90)
    check("chat danae vía dispatcher", _d.get("success") is True and _d.get("via") == "poli:danae" and bool(_d.get("response")),
          str(_d)[:100])
    # agente no registrado → 404
    try:
        http_json_post(auth(f"{BASE}/ddp/agent/chat"), {"agente": "fantasma", "mensaje": "hola"}, 15)
        check("agente no registrado rechazado", False, "debió fallar")
    except urllib.error.HTTPError as _e:
        check("agente no registrado rechazado", _e.code == 404, f"code={_e.code}")
except Exception as e:
    check("registro ^AGENTES(routing)", False, str(e)[:100])
    check("4 nuevos registrados", False, "")
    check("chat vega vía dispatcher", False, "")
    check("chat danae vía dispatcher", False, "")
    check("agente no registrado rechazado", False, "")

print(f"\n{'='*50}\nRESULTADO: {len(PASS)} ✅  |  {len(FAIL)} ❌")
if FAIL:
    print("FALLOS:", " | ".join(FAIL))
    sys.exit(1)
print("TODO VERDE — el ecosistema sigue sano. 🌱")
