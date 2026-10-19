"""test_contract_persist.py — el contrato sobrevive a un reinicio (PDB real).

Prueba el ciclo completo con una PDB temporal:
  crear contrato -> guardar (_save_state) -> "reiniciar" (limpiar memoria +
  _load_state) -> el contrato sigue ahí con su dueño, checkpoint y traza.
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="ctrpersist_")
os.environ["PDB_PATH"] = os.path.join(_TMP, "t.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server as T          # noqa: E402
import task_contract as TC  # noqa: E402

OK = 0
FAIL = 0


def check(name, cond, detail=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"PASA   {name}")
    else:
        FAIL += 1
        print(f"FALLA  {name}")
        if detail:
            print(f"       {detail}")


def main() -> int:
    # 1. Crear y trabajar un contrato
    r = TC.tool_contract_create({
        "objective": "persistir contrato entre nodos",
        "criterion": "sobrevive a reinicio con dueño y checkpoint",
        "author": "gonzalo",
    })
    cid = r["contract"]["contract_id"]
    TC.tool_contract_claim({"contract_id": cid, "node": "hermes-pc"})
    TC.tool_contract_handoff({"contract_id": cid, "node": "hermes-pc",
                              "outcome": "free", "checkpoint": "falta validar en asus"})
    TC.tool_contract_claim({"contract_id": cid, "node": "hermes-asus"})

    antes = dict(TC._store()[cid])
    check("P1 contrato en memoria", antes["claimed_by"] == "hermes-asus")

    # 2. Guardar a PDB. _save_state lanza _pdb_save_all en un HILO en background
    #    (para no bloquear el handler), así que hay que esperar a que acabe:
    #    sin esto el test comprueba antes de que el contrato llegue al disco.
    T._save_state()
    import time as _t
    for _ in range(100):                      # hasta 10 s
        conn = T._pdb.pdb_connect()
        n = conn.execute(
            "SELECT COUNT(*) FROM _globals WHERE ns='STATE' AND subkey LIKE '%global:contract:%'"
        ).fetchone()[0]
        conn.close()
        if n > 0:
            break
        _t.sleep(0.1)
    check("P2 estado guardado en PDB", n > 0, f"filas contract en PDB: {n}")

    # 3. "Reiniciar": limpiar memoria y recargar de PDB
    TC._store().clear()
    check("P3 memoria vaciada", len(TC._store()) == 0)
    T._load_state()

    # 4. ¿Sobrevivió?
    store = TC._store()
    check("P4 el contrato sobrevive al reinicio", cid in store,
          f"contratos tras recarga: {list(store)}")
    if cid in store:
        c = store[cid]
        check("P5 conserva el dueño", c.get("claimed_by") == "hermes-asus",
              f"dueño={c.get('claimed_by')}")
        check("P6 conserva el checkpoint",
              bool(c.get("checkpoints")) and "asus" in c["checkpoints"][-1]["note"],
              f"checkpoints={c.get('checkpoints')}")
        check("P7 conserva la traza",
              len(c.get("history") or []) >= 3,
              f"eventos={len(c.get('history') or [])}")
        check("P8 conserva objetivo y criterio",
              c.get("objective") and c.get("criterion"))

    # 5. Tras el reinicio, el otro nodo NO puede reclamarlo (sigue ocupado)
    if cid in store:
        bad = TC.tool_contract_claim({"contract_id": cid, "node": "hermes-mvm"})
        check("P9 el conflicto se mantiene tras reinicio", bad["ok"] is False)

    print(f"\n{OK + FAIL} checks · {OK} PASA · {FAIL} FALLA")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
