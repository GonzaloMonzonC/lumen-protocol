"""test_contract_autopersist.py — el contrato se persiste SOLO, sin ayuda del test.

El test anterior (test_contract_persist.py) llamaba a _save_state() a mano, y eso
ocultaba el fallo real: las tools de contrato NO persistían por sí mismas. En uso
real (dos Hermes en máquinas distintas) el contrato vivía solo en la memoria del
proceso y moría al reiniciar.

Este test simula el uso REAL: llamar la tool y comprobar que el dato está en el
disco sin que el test guarde nada.
"""
import os
import sqlite3
import sys
import tempfile
import time

_TMP = tempfile.mkdtemp(prefix="ctr_auto_")
_DB = os.path.join(_TMP, "t.db")
os.environ["PDB_PATH"] = _DB
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


def filas_contract(timeout=10.0):
    """Cuenta filas de contract en disco, usando pdb_connect (crea el esquema).

    NO usar sqlite3.connect a pelo: una PDB nueva se abre sin esquema y da
    "no such table: _globals". Es el mismo bug H7 que documenta pdb_connect.
    """
    fin = time.time() + timeout
    n = 0
    while time.time() < fin:
        try:
            conn = T._pdb.pdb_connect()
            n = conn.execute(
                "SELECT COUNT(*) FROM _globals WHERE ns='STATE' AND subkey LIKE '%global:contract:%'"
            ).fetchone()[0]
            conn.close()
        except Exception:
            n = 0
        if n > 0:
            return n
        time.sleep(0.1)
    return n


def main() -> int:
    # 1. Crear SOLO con la tool. El test no guarda nada.
    r = TC.tool_contract_create({
        "objective": "autopersistencia",
        "criterion": "aparece en disco sin que el test guarde",
        "author": "gonzalo",
    })
    cid = r["contract"]["contract_id"]

    n = filas_contract()
    check("A1 contract_create persiste solo", n > 0, f"filas en PDB: {n}")

    # 2. Handoff SOLO con la tool
    TC.tool_contract_claim({"contract_id": cid, "node": "hermes-pc"})
    TC.tool_contract_handoff({"contract_id": cid, "node": "hermes-pc",
                              "outcome": "free", "checkpoint": "pendiente validar"})

    # 3. Simular OTRO nodo: proceso nuevo, memoria limpia, lee del disco
    TC._store().clear()
    T._load_state()
    store = TC._store()
    check("A2 otro nodo ve el contrato tras reiniciar", cid in store,
          f"contratos tras recarga: {list(store)}")
    if cid in store:
        c = store[cid]
        check("A3 conserva el checkpoint del handoff",
              bool(c.get("checkpoints")), f"checkpoints={c.get('checkpoints')}")

    print(f"\n{OK + FAIL} checks · {OK} PASA · {FAIL} FALLA")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
