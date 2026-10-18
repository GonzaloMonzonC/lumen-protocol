#!/usr/bin/env python3
"""test_rag_operativo.py — H1

Tres capas rotas, tres comprobaciones:
  1. sin sqlite_vec  -> pdb_vec_search devuelve {success:false, reason} y NUNCA
     una excepcion / -32603. Un agente debe poder degradar con elegancia.
  2. con sqlite_vec  -> las tablas vec0 existen tras _init_vec()
  3. escritura       -> pdb_embed esta EXPUESTA (sin escritura, la busqueda no
     tiene que devolver ni con las deps puestas)

Usa PDB temporal. Marca [rag] las que necesitan fastembed.
    python test_rag_operativo.py [-v]
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def find_pdb():
    for parent in Path(__file__).resolve().parents:
        cand = parent / "implementations/mcp-servers/pdb"
        if (cand / "pdb_tools.py").is_file():
            return cand
    return Path.home() / "Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"


# Corre dentro de un subproceso con PDB_PATH temporal y sys.path apuntando al server.
PROBE = r"""
import json, os, sqlite3, sys
res = {}

# 1. estado del subsistema (no debe lanzar nunca)
try:
    import pdb_tools as t
    st = t._vec_status()
    res["status"] = st
    res["status_type"] = type(st).__name__
except Exception as e:
    res["status_error"] = f"{type(e).__name__}: {e}"

# 2. pdb_vec_search sin deps / sin indice: resultado estructurado
try:
    import pdb_tools as t
    r = t.tool_vec_search({"query": "prueba"})
    res["vec_search"] = r
    res["vec_search_is_dict"] = isinstance(r, dict)
    res["vec_search_success_key"] = "success" in r if isinstance(r, dict) else False
except Exception as e:
    res["vec_search_raised"] = f"{type(e).__name__}: {e}"

# 3. tablas vec0 presentes?
try:
    import pdb_tools as t
    c = t._get_conn()
    names = [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%vec%'")]
    res["vec_tables"] = names
except Exception as e:
    res["vec_tables_error"] = f"{type(e).__name__}: {e}"

# 4. TOOLS expuestas: pdb_embed debe estar
try:
    import pdb_tools as t
    res["tools"] = sorted(x["name"] for x in t.TOOLS)
    res["handlers"] = sorted(t.HANDLERS)
except Exception as e:
    res["tools_error"] = f"{type(e).__name__}: {e}"

# 5. escritura real (si hay fastembed)
try:
    import importlib.util as iu
    if iu.find_spec("fastembed") and iu.find_spec("sqlite_vec"):
        import pdb_tools as t
        st = t._vec_status()
        if st.get("status") == "ready":
            w = t.tool_embed({"texts": ["El rápido zorro marrón salta sobre el perro"],
                              "source": "test"})
            res["embed_write"] = {"success": w.get("success"), "error": w.get("error")}
            s = t.tool_vec_search({"query": "zorro marrón", "limit": 3})
            res["embed_read"] = {"success": s.get("success"),
                                 "count": s.get("count"),
                                 "top": (s.get("results") or [{}])[0].get("score")}
        else:
            res["embed_write"] = {"skipped": "subsistema no ready", "status": st}
    else:
        res["embed_write"] = {"skipped": "faltan deps"}
except Exception as e:
    res["embed_write"] = {"raised": f"{type(e).__name__}: {e}"}

print("@@RES@@" + json.dumps(res, default=str))
"""


def main():
    verbose = "-v" in sys.argv
    pdbdir = find_pdb()
    if not (pdbdir / "pdb_tools.py").is_file():
        print(f"SKIP: no encuentro {pdbdir}/pdb_tools.py")
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="h1_rag_"))
    testdb = tmp / "rag.db"

    env = dict(os.environ, PDB_PATH=str(testdb), PYTHONIOENCODING="utf-8",
               PYTHONPATH=str(pdbdir))
    for k in ("PDB_DB",):
        env.pop(k, None)

    r = subprocess.run([sys.executable, "-c", PROBE], cwd=str(pdbdir), env=env,
                       capture_output=True, text=True, timeout=300,
                       encoding="utf-8")
    out = None
    for line in (r.stdout or "").splitlines():
        if line.startswith("@@RES@@"):
            out = json.loads(line[len("@@RES@@"):])
            break

    if out is None:
        print("FALLO: el probe no devolvio resultado")
        print("stdout:", (r.stdout or "")[-800:])
        print("stderr:", (r.stderr or "")[-800:])
        return 1

    if verbose:
        print(json.dumps(out, indent=2, ensure_ascii=False))

    fails = []

    # ── 1. el estado no puede petar ni mentir ──
    if "status_error" in out:
        fails.append(f"_vec_status() lanzo excepcion: {out['status_error']}")
    else:
        st = out.get("status") or {}
        if out.get("status_type") != "dict":
            fails.append(f"_vec_status() devolvio {out.get('status_type')}, esperado dict")
        if st.get("status") not in ("ready", "no_sqlite_vec", "no_tables", "error"):
            fails.append(f"status desconocido: {st.get('status')!r}")
        print(f"  subsistema: {st.get('status')} (reason={st.get('reason')})")

    # ── 2. pdb_vec_search NUNCA debe lanzar: siempre dict con 'success' ──
    if "vec_search_raised" in out:
        fails.append(f"pdb_vec_search LANZO excepcion (esto es el -32603 de H1): "
                     f"{out['vec_search_raised']}")
    else:
        vs = out.get("vec_search") or {}
        if not out.get("vec_search_is_dict"):
            fails.append("pdb_vec_search no devolvio dict")
        elif not out.get("vec_search_success_key"):
            fails.append(f"pdb_vec_search no devolvio 'success': {vs}")
        else:
            print(f"  vec_search: success={vs.get('success')} reason={vs.get('reason')!r}")
            if vs.get("success") is False and not vs.get("reason"):
                fails.append("success:false sin 'reason': el agente no sabe que pasa")

    # ── 3. coherencia entre status y tablas vec0 ──
    tables = out.get("vec_tables") or []
    st = out.get("status") or {}
    if st.get("status") == "ready" and not tables:
        fails.append("status='ready' pero no existen tablas vec0: el status miente")
    if st.get("status") != "ready" and tables:
        fails.append(f"status={st.get('status')!r} pero las tablas existen: {tables}")
    print(f"  tablas vec0: {tables or '[]'}")

    # ── 4. pdb_embed EXPUESTA (sin escritura el pipeline esta a medias) ──
    tools = out.get("tools") or []
    handlers = out.get("handlers") or []
    if "pdb_embed" not in tools:
        fails.append("pdb_embed NO esta en TOOLS: se expone la lectura sin la escritura")
    else:
        print(f"  pdb_embed expuesta: si  (TOOLS={len(tools)} / HANDLERS={len(handlers)})")
    if "pdb_embed" in tools and "pdb_embed" not in handlers:
        fails.append("pdb_embed esta en TOOLS pero no en HANDLERS")

    # ── 5. si hay deps, el pipeline completo debe funcionar ──
    ew = out.get("embed_write") or {}
    if "raised" in ew:
        fails.append(f"tool_embed lanzo: {ew['raised']}")
    elif ew.get("skipped"):
        print(f"  [rag] escritura: SKIP ({ew['skipped']})")
    elif ew.get("success") is False:
        fails.append(f"pdb_embed fallo con deps presentes: {ew.get('error')}")
    else:
        print(f"  [rag] escritura: OK")
        er = out.get("embed_read") or {}
        if er.get("success") is not True:
            fails.append(f"pdb_vec_search fallo tras indexar: {er}")
        else:
            print(f"  [rag] lectura: OK ({er.get('count')} resultados, "
                  f"top score {er.get('top')})")
            top = er.get("top")
            if top is not None and top <= 0.5:
                fails.append(f"score del match {top} <= 0.5: recuperacion irrelevante")

    print()
    if fails:
        print(f"FALLO ({len(fails)})")
        for f in fails:
            print(f"   - {f}")
        return 1
    print("PASS: RAG con las tres capas coherentes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
