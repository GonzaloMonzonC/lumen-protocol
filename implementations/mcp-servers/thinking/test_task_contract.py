"""test_task_contract.py — criterio de aceptación del contrato de tarea (pieza 1).

Verifica el flujo mínimo de colaboración multi-nodo del doc 07:
contrato -> reclamación -> conflicto -> handoff con checkpoint -> nuevo dueño -> traza.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
    # ── Contrato sin criterio: rechazado ──────────────────────────────
    r = TC.tool_contract_create({"objective": "hacer algo", "author": "h1"})
    check("C1 sin criterio NO es válido", r["valid"] is False)
    check("C1b el motivo menciona el criterio",
          "criterion" in r["content"][0]["text"].lower())

    # ── Contrato completo ─────────────────────────────────────────────
    r = TC.tool_contract_create({
        "objective": "analizar repo X",
        "criterion": "informe con 3 hallazgos verificados",
        "inputs": ["url-del-repo"],
        "outputs": ["docs/informe.md"],
        "limits": ["no tocar main"],
        "role": "verificador",
        "author": "gonzalo",
    })
    c = r["contract"]
    cid = c["contract_id"]
    check("C2 contrato válido creado", r["valid"] is True and cid.startswith("ctr_"))
    check("C2b nace libre", c["claim_status"] == TC.CLAIM_FREE)
    check("C2c guarda entradas/salidas/límites",
          c["inputs"] == ["url-del-repo"] and c["outputs"] == ["docs/informe.md"]
          and c["limits"] == ["no tocar main"])

    # ── Reclamación: solo uno lo consigue ─────────────────────────────
    a = TC.tool_contract_claim({"contract_id": cid, "node": "hermes-pc"})
    b = TC.tool_contract_claim({"contract_id": cid, "node": "hermes-asus"})
    check("C3 primer nodo reclama", a["ok"] is True)
    check("C3b segundo nodo NO puede (conflicto detectado)", b["ok"] is False)
    check("C3c el mensaje dice quién lo tiene", "hermes-pc" in b["content"][0]["text"])

    # ── Handoff con checkpoint ────────────────────────────────────────
    h = TC.tool_contract_handoff({
        "contract_id": cid, "node": "hermes-pc", "outcome": "free",
        "checkpoint": "hecho: 3 hallazgos en docs/informe.md; pendiente: validar en Asus",
    })
    check("C4 handoff del dueño", h["ok"] is True)
    check("C4b checkpoint guardado",
          h["contract"]["checkpoints"][-1]["by"] == "hermes-pc")

    # ── El segundo nodo ahora sí puede ────────────────────────────────
    c2 = TC.tool_contract_claim({"contract_id": cid, "node": "hermes-asus"})
    check("C5 tras handoff el otro nodo reclama", c2["ok"] is True)
    check("C5b el dueño cambió", c2["contract"]["claimed_by"] == "hermes-asus")

    # ── Traza (pieza 3) ───────────────────────────────────────────────
    hist = c2["contract"]["history"]
    kinds = [h["kind"] for h in hist]
    check("C6 la traza registra claim y release", "claim" in kinds
          and any(k.startswith("release") for k in kinds))
    check("C6b la traza identifica al actor",
          all(h.get("actor") for h in hist))

    # ── Cerrar como done y que no se pueda reclamar ───────────────────
    TC.tool_contract_handoff({"contract_id": cid, "node": "hermes-asus", "outcome": "done"})
    d = TC.tool_contract_claim({"contract_id": cid, "node": "hermes-pc"})
    check("C7 un contrato 'done' no se puede reclamar", d["ok"] is False)

    # ── No-dueño no puede liberar ─────────────────────────────────────
    r2 = TC.tool_contract_create({"objective": "x", "criterion": "y"})
    cid2 = r2["contract"]["contract_id"]
    TC.tool_contract_claim({"contract_id": cid2, "node": "hermes-pc"})
    bad = TC.tool_contract_handoff({"contract_id": cid2, "node": "hermes-asus"})
    check("C8 un nodo no puede liberar lo que no tiene", bad["ok"] is False)

    print(f"\n{OK + FAIL} checks · {OK} PASA · {FAIL} FALLA")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
