#!/usr/bin/env python3
"""test_budget.py — H2: presupuesto de tool calls configurable y NO heredado.

Dos casos, ambos contra PDB temporal (nunca la real):

  test_budget_configurable:
      LUMEN_THINKING_MAX_CALLS=5 -> la 6ª llamada de ESCRITURA falla con -32001
      y el mensaje dice cómo salir. Las de SOLO LECTURA siguen funcionando
      después del bloqueo.

  test_budget_no_se_hereda:
      Se escribe a mano una sesión 'default' con tool_calls == max (el formato
      exacto que produce Session.to_dict). Se arranca el server: la primera
      llamada debe funcionar (contador reseteado al arrancar), no -32001.
      Este es EL test del brick: sin el self-heal, la sesión está condenada.

Sin dependencias externas. Uso:
    python test_budget.py [-v]
Exit 0 si los dos pasan.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def find_thinking():
    for parent in Path(__file__).resolve().parents:
        cand = parent / "implementations/mcp-servers/thinking"
        if (cand / "server.py").is_file():
            return cand
    return Path.home() / "Documents/GitHub/lumen-protocol/implementations/mcp-servers/thinking"


class Server:
    """Arranca server.py por stdio contra una PDB temporal."""

    def __init__(self, think: Path, pdb: Path, env_extra=None):
        env = dict(os.environ, PDB_PATH=str(pdb), PYTHONUNBUFFERED="1",
                   PYTHONIOENCODING="utf-8")
        env.pop("LUMEN_THINKING_MAX_CALLS", None)
        if env_extra:
            env.update(env_extra)
        self.p = subprocess.Popen(
            [sys.executable, str(think / "server.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, cwd=str(think), text=True, encoding="utf-8")
        self._id = 0

    def send(self, method, params=None):
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("server cerro stdout")
        return json.loads(line)

    def notify(self, method, params=None):
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method,
                                       "params": params or {}}) + "\n")
        self.p.stdin.flush()

    def init(self):
        return self.send("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                        "clientInfo": {"name": "budget-test", "version": "0"}})

    def call(self, tool, args):
        return self.send("tools/call", {"name": tool, "arguments": args})

    def text(self, resp):
        if "result" in resp:
            c = resp["result"].get("content") or []
            return c[0].get("text", "") if c else ""
        return ""

    def err_code(self, resp):
        return (resp.get("error") or {}).get("code")

    def close(self):
        try:
            self.p.terminate()
            self.p.wait(timeout=5)
        except Exception:
            try:
                self.p.kill()
            except Exception:
                pass


def test_budget_configurable(think, tmp, verbose=False):
    """Con tope 5: la 6ª escritura falla con la salida en el mensaje; lecturas siguen."""
    fails = []
    pdb = tmp / "budget_conf.db"
    s = Server(think, pdb, {"LUMEN_THINKING_MAX_CALLS": "5"})
    try:
        s.init()
        s.notify("notifications/initialized")

        # session_init con max_calls explicito: comprobamos que viaja el tope
        r = s.call("session_init", {"label": "budget-test", "session_id": "bt", "max_calls": 5})
        txt = s.text(r)
        if "5" not in txt:
            fails.append(f"session_init no reporta el tope 5: {txt[:120]!r}")
        if verbose:
            print(f"    session_init -> {txt.splitlines()[-1] if txt else '(vacio)'}")

        # llamadas de escritura que cuentan: pattern_record
        escrituras_ok, bloqueo = 0, None
        for i in range(1, 9):
            r = s.call("pattern_record", {"pattern_name": f"p{i}",
                                          "description": f"desc {i}",
                                          "session_id": "bt"})
            if s.err_code(r) == -32001:
                bloqueo = i
                msg = (r.get("error") or {}).get("message", "")
                if verbose:
                    print(f"    bloqueo en la llamada {i}: {msg[:100]}...")
                if "session_init" not in msg:
                    fails.append("el mensaje de -32001 no ofrece la salida session_init")
                if "LUMEN_THINKING_MAX_CALLS" not in msg:
                    fails.append("el mensaje de -32001 no menciona LUMEN_THINKING_MAX_CALLS")
                break
            escrituras_ok += 1

        if bloqueo is None:
            fails.append(f"no bloqueo nunca con tope 5 ({escrituras_ok} escrituras pasaron)")
        elif not (4 <= bloqueo <= 7):
            fails.append(f"bloqueo en la llamada {bloqueo}, esperado ~5-7 (tope 5 + lecturas de init)")

        # AHORA lo importante: las de solo lectura deben seguir vivas
        for tool, args in (("state_snapshot", {"session_id": "bt"}),
                           ("session_list", {"session_id": "bt"}),
                           ("context_estimate", {"session_id": "bt"})):
            r = s.call(tool, args)
            if s.err_code(r) == -32001:
                fails.append(f"{tool} bloqueada por el presupuesto: deberia ser solo lectura")
            elif "error" in r:
                fails.append(f"{tool} fallo con {r.get('error')}")
            elif verbose:
                print(f"    {tool} tras el bloqueo -> OK")

        # Y una escritura sigue bloqueada (control negativo: el tope existe de verdad)
        r = s.call("pattern_record", {"pattern_name": "p_extra", "description": "x",
                                      "session_id": "bt"})
        if s.err_code(r) != -32001:
            fails.append("una escritura paso DESPUES del bloqueo: el tope no se aplica")
    finally:
        s.close()
    return fails


def test_budget_no_se_hereda(think, tmp, verbose=False):
    """Sesion persistida en el tope -> arranca en 0. Este es el test del brick."""
    fails = []
    pdb = tmp / "budget_heredado.db"

    # 1. crear la PDB con una sesion ya en el tope, formato de Session.to_dict
    conn = sqlite3.connect(str(pdb))
    conn.execute("""CREATE TABLE IF NOT EXISTS _globals (
                      ns TEXT NOT NULL, subkey BLOB NOT NULL, value TEXT,
                      PRIMARY KEY (ns, subkey)) WITHOUT ROWID""")
    info = {
        "label": "default", "chains": {}, "assumptions": [],
        "next_assumption_id": 1, "model": {}, "works": [], "next_work_id": 1,
        "patterns": [], "next_pattern_id": 1, "decisions": [],
        "next_decision_id": 1, "bridges": [], "wiki": {}, "model_name": "",
        "tool_calls": 100,          # <-- EN EL TOPE: la sesion esta condenada
        "created_at": time.time(), "updated_at": time.time(), "feeling": None,
    }
    conn.execute("INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                 ("STATE", b"session:default:info", json.dumps(info)))
    conn.commit()
    conn.close()

    if verbose:
        print(f"    PDB sembrada con session:default tool_calls=100")

    s = Server(think, pdb)          # tope por defecto (100)
    try:
        s.init()
        s.notify("notifications/initialized")
        r = s.call("state_snapshot", {"session_id": "default"})
        if s.err_code(r) == -32001:
            fails.append("BRICK: la sesion restaurada responde -32001 en la 1a llamada")
        elif "error" in r:
            fails.append(f"state_snapshot fallo: {r.get('error')}")

        # Y una escritura tambien debe pasar (contador reseteado)
        r = s.call("pattern_record", {"pattern_name": "tras_arranque",
                                      "description": "la sesion revive",
                                      "session_id": "default"})
        if s.err_code(r) == -32001:
            fails.append("BRICK: la primera ESCRITURA tras reiniciar sigue bloqueada")
        elif verbose:
            print(f"    escritura tras arranque -> OK (la sesion revive)")
    finally:
        s.close()
    return fails


def main():
    verbose = "-v" in sys.argv
    think = find_thinking()
    if not (think / "server.py").is_file():
        print(f"SKIP: no encuentro {think}/server.py")
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="h2_budget_"))
    print(f"thinking : {think}")
    print(f"tmp      : {tmp}\n")

    all_fails = []
    for name, fn in (("test_budget_configurable", test_budget_configurable),
                     ("test_budget_no_se_hereda", test_budget_no_se_hereda)):
        print(f"[{name}]")
        try:
            fails = fn(think, tmp, verbose)
        except Exception as e:
            fails = [f"excepcion: {type(e).__name__}: {e}"]
        if fails:
            print(f"  FAIL")
            for f in fails:
                print(f"     - {f}")
            all_fails.extend([f"{name}: {f}" for f in fails])
        else:
            print(f"  PASS")

    print()
    if all_fails:
        print(f"RESULTADO: {len(all_fails)} fallo(s)")
        return 1
    print("RESULTADO: 2/2 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
