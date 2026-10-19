"""test_team_session.py — sesión de equipo (pieza 3).

Criterio clave (Smith): "La sesión es la VISTA, el contrato es la VERDAD. Se
rompe si la sesión se vuelve además el registro durable."

Estos tests verifican esa separación:
  - el mando se deriva del contrato, no se guarda aparte
  - el checkpoint ES la traza del contrato
  - dos nodos no pueden tener el mando a la vez
  - la dotación sí es propia de la sesión
"""
import os
import sys
import tempfile

os.environ["PDB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="ses_"), "t.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server as T          # noqa: E402
import team_session as S    # noqa: E402

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
    # ── Abrir turno ───────────────────────────────────────────────────
    r = S.tool_session_open({
        "objective": "auditar repo X",
        "criterion": "informe con 3 hallazgos",
        "members": ["hermes-pc", "hermes-asus"],
        "author": "gonzalo",
    })
    sid = r["session"]["session_id"]
    check("S1 turno abierto y válido", r["valid"] is True and sid.startswith("ses_"))
    check("S2 nace libre (nadie tiene el mando)", S.derive_state(r["session"]) == S.ST_FREE)

    # ── Criterio obligatorio ──────────────────────────────────────────
    bad = S.tool_session_open({"objective": "sin criterio"})
    check("S3 sin criterio NO se abre", bad["valid"] is False)

    # ── Tomar el mando ────────────────────────────────────────────────
    a = S.tool_session_claim({"session_id": sid, "node": "hermes-pc"})
    check("S4 hermes-pc toma el mando", a["ok"] is True)
    check("S5 estado derivado = corriendo", S.derive_state(a["session"]) == S.ST_RUNNING)
    check("S6 el mando sale del CONTRATO (no duplicado)",
          a["session"]["contract"]["claimed_by"] == "hermes-pc"
          and "owner" not in a["session"])

    # ── Segundo nodo NO puede ─────────────────────────────────────────
    b = S.tool_session_claim({"session_id": sid, "node": "hermes-asus"})
    check("S7 segundo nodo rechazado (exclusión)", b["ok"] is False)
    check("S8 el rechazo dice quién tiene el mando", "hermes-pc" in b["content"][0]["text"])

    # ── Nodo fuera de la dotación no puede tomar el mando ─────────────
    out = S.tool_session_claim({"session_id": sid, "node": "hermes-mvm"})
    check("S9 nodo fuera de dotación no puede reclamar", out["ok"] is False)

    # ── Handoff con checkpoint ────────────────────────────────────────
    h = S.tool_session_handoff({"session_id": sid, "node": "hermes-pc",
                                "outcome": "free",
                                "checkpoint": "hecho: 3 hallazgos; pendiente: validar"})
    check("S10 handoff del que tiene el mando", h["ok"] is True)
    check("S11 estado = esperando-humano", S.derive_state(h["session"]) == S.ST_WAITING)
    check("S12 el checkpoint vive en la TRAZA del contrato",
          bool(h["session"]["contract"]["checkpoints"])
          and bool(h["session"]["contract"]["history"]))

    # ── Otro nodo retoma ──────────────────────────────────────────────
    c = S.tool_session_claim({"session_id": sid, "node": "hermes-asus"})
    check("S13 tras handoff, el otro nodo retoma", c["ok"] is True)
    check("S14 vuelve a corriendo", S.derive_state(c["session"]) == S.ST_RUNNING)

    # ── Cerrar ────────────────────────────────────────────────────────
    d = S.tool_session_handoff({"session_id": sid, "node": "hermes-asus", "outcome": "done"})
    check("S15 cerrado", S.derive_state(d["session"]) == S.ST_CLOSED)
    e = S.tool_session_claim({"session_id": sid, "node": "hermes-pc"})
    check("S16 un turno cerrado no se puede reclamar", e["ok"] is False)

    # ── Dotación: sí es propia de la sesión ───────────────────────────
    r2 = S.tool_session_open({"objective": "otro", "criterion": "ok", "members": ["hermes-pc"]})
    sid2 = r2["session"]["session_id"]
    m1 = S.tool_session_member({"session_id": sid2, "node": "hermes-asus", "action": "add"})
    check("S17 añadir miembro a la dotación", m1["ok"] is True
          and "hermes-asus" in m1["session"]["members"])
    m2 = S.tool_session_member({"session_id": sid2, "node": "hermes-asus", "action": "add"})
    check("S18 no se duplica un miembro", m2["ok"] is False)
    S.tool_session_claim({"session_id": sid2, "node": "hermes-asus"})
    m3 = S.tool_session_member({"session_id": sid2, "node": "hermes-asus", "action": "remove"})
    check("S19 no se puede sacar a quien tiene el mando", m3["ok"] is False)
    m4 = S.tool_session_member({"session_id": sid2, "node": "hermes-pc", "action": "remove"})
    check("S20 sí se puede sacar a quien NO tiene el mando", m4["ok"] is True)

    # ── Línea de turnos (lo que se pinta en el backoffice) ────────────
    lst = S.tool_session_list({})
    txt = lst["content"][0]["text"]
    check("S21 la línea de turnos lista ambos", sid in txt and sid2 in txt)
    check("S22 ordena corriendo antes que cerrado",
          txt.index("🟢") < txt.index("✅") if "🟢" in txt and "✅" in txt else True)

    print(f"\n{OK + FAIL} checks · {OK} PASA · {FAIL} FALLA")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
