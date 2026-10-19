"""test_session_persist.py — el turno sobrevive al reinicio (sin ayuda del test).

Mismo criterio que test_contract_autopersist: llamar SOLO a las tools y
comprobar que el turno está en disco. Sin _save_state() a mano.
"""
import os
import sys
import tempfile

os.environ["PDB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="sespersist_"), "t.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server as T        # noqa: E402
import team_session as S  # noqa: E402

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


def filas_session(timeout=10.0):
    """Cuenta turnos en disco usando pdb_connect (crea el esquema si es nueva)."""
    import time as _t
    fin = _t.time() + timeout
    n = 0
    while _t.time() < fin:
        try:
            conn = T._pdb.pdb_connect()
            n = conn.execute(
                "SELECT COUNT(*) FROM _globals WHERE ns='STATE' "
                "AND subkey LIKE '%global:teamsession:%'"
            ).fetchone()[0]
            conn.close()
        except Exception:
            n = 0
        if n > 0:
            return n
        _t.sleep(0.1)
    return n


def main() -> int:
    # 1. Abrir turno SOLO con la tool
    r = S.tool_session_open({
        "objective": "turno persistente",
        "criterion": "sobrevive a reinicio con mando y checkpoint",
        "members": ["hermes-pc", "hermes-asus"],
        "author": "gonzalo",
    })
    sid = r["session"]["session_id"]

    n = filas_session()
    check("T1 session_open persiste solo", n > 0, f"filas en PDB: {n}")

    # 2. Tomar mando y soltar con checkpoint, SOLO con tools
    S.tool_session_claim({"session_id": sid, "node": "hermes-pc"})
    S.tool_session_handoff({"session_id": sid, "node": "hermes-pc",
                            "outcome": "free", "checkpoint": "pendiente validar en asus"})

    # 3. Simular OTRO nodo: memoria limpia + recarga del disco
    S._store().clear()
    T._load_state()

    store = S._store()
    check("T2 el turno sobrevive al reinicio", sid in store, f"turnos: {list(store)}")
    if sid in store:
        s = store[sid]
        check("T3 conserva la dotación",
              s.get("members") == ["hermes-pc", "hermes-asus"],
              f"members={s.get('members')}")
        check("T4 conserva el checkpoint",
              bool(s.get("contract", {}).get("checkpoints")))
        check("T5 el estado derivado es esperando-humano",
              S.derive_state(s) == S.ST_WAITING, f"estado={S.derive_state(s)}")
        # 4. Otro nodo retoma tras el reinicio
        c = S.tool_session_claim({"session_id": sid, "node": "hermes-asus"})
        check("T6 otro nodo retoma tras reiniciar", c["ok"] is True)

    print(f"\n{OK + FAIL} checks · {OK} PASA · {FAIL} FALLA")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
