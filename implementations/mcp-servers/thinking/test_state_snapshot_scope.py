#!/usr/bin/env python3
"""test_state_snapshot_scope.py — H4

`state_snapshot` sumaba TODAS las sesiones y usaba el contador global del
proceso. Un agente en una sesión vacía veía chains y llamadas de otro, y la tool
se documenta como "system health" -> se lee como salud propia.

Este test monta dos sesiones con actividad distinta y exige:
  - state_snapshot(session_id=A) reporta SOLO lo de A
  - state_snapshot() sin session_id cuenta como 'default', NO agrega
  - state_global() sí agrega, y lo dice

Sin dependencias. PDB temporal.
    python test_state_snapshot_scope.py [-v]
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def find_thinking():
    for parent in Path(__file__).resolve().parents:
        cand = parent / "implementations/mcp-servers/thinking"
        if (cand / "server.py").is_file():
            return cand
    return Path.home() / "Documents/GitHub/lumen-protocol/implementations/mcp-servers/thinking"


class Server:
    def __init__(self, think, pdb):
        env = dict(os.environ, PDB_PATH=str(pdb), PYTHONUNBUFFERED="1",
                   PYTHONIOENCODING="utf-8")
        env.pop("LUMEN_THINKING_MAX_CALLS", None)
        self.p = subprocess.Popen([sys.executable, str(think / "server.py")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=env, cwd=str(think),
                                  text=True, encoding="utf-8")
        self._id = 0

    def _send(self, msg):
        self.p.stdin.write(json.dumps(msg) + "\n"); self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("server cerro stdout")
        return json.loads(line)

    def init(self):
        return self._send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                      "clientInfo": {"name": "h4", "version": "0"}}})

    def notify(self, method):
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method,
                                       "params": {}}) + "\n"); self.p.stdin.flush()

    def call(self, tool, args):
        self._id += 1
        return self._send({"jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                           "params": {"name": tool, "arguments": args}})

    def text(self, r):
        if "result" in r:
            c = r["result"].get("content") or []
            return c[0].get("text", "") if c else ""
        return f"<error {r.get('error')}>"

    def close(self):
        try:
            self.p.terminate(); self.p.wait(timeout=5)
        except Exception:
            try: self.p.kill()
            except Exception: pass


def num(txt, pat):
    """Extrae el entero que precede a un sufijo, p.ej. '3c' -> 3."""
    m = re.search(r"(\d+)" + pat, txt)
    return int(m.group(1)) if m else None


def main():
    verbose = "-v" in sys.argv
    think = find_thinking()
    if not (think / "server.py").is_file():
        print(f"SKIP: no encuentro {think}/server.py"); return 0

    tmp = Path(tempfile.mkdtemp(prefix="h4_scope_"))
    s = Server(think, tmp / "h4.db")
    fails = []
    try:
        s.init(); s.notify("notifications/initialized")

        # Sesión A: 1 cadena con 1 pensamiento
        s.call("session_init", {"label": "A", "session_id": "A"})
        s.call("sequential_thinking", {"thought": "unico pensamiento de A",
                                       "nextThoughtNeeded": False, "totalThoughts": 1,
                                       "session_id": "A"})

        # Sesión B: 6 pensamientos, cada uno en su propia cadena
        # (sequential_thinking sin chainId crea cadena nueva: server.py:1535)
        s.call("session_init", {"label": "B", "session_id": "B"})
        for i in range(6):
            s.call("sequential_thinking", {"thought": f"pensamiento {i} de B",
                                           "nextThoughtNeeded": False, "totalThoughts": 1,
                                           "session_id": "B"})

        # --- 1. A debe ver SOLO lo suyo ---
        ta = s.text(s.call("state_snapshot", {"session_id": "A"}))
        if verbose: print(f"    A -> {ta}")
        ca, tha = num(ta, "c"), num(ta, "t")
        if ca != 1:
            fails.append(f"state_snapshot(A) dice {ca} cadenas, esperado 1 -> {ta!r}")
        if tha != 1:
            fails.append(f"state_snapshot(A) dice {tha} pensamientos, esperado 1 -> {ta!r}")
        if "[A]" not in ta:
            fails.append(f"la salida no identifica la sesion: {ta!r}")

        # --- 2. B debe ver lo suyo, no la suma ---
        tb = s.text(s.call("state_snapshot", {"session_id": "B"}))
        if verbose: print(f"    B -> {tb}")
        cb, thb = num(tb, "c"), num(tb, "t")
        if cb != 6:
            fails.append(f"state_snapshot(B) dice {cb} cadenas, esperado 6 -> {tb!r}")
        if thb != 6:
            fails.append(f"state_snapshot(B) dice {thb} pensamientos, esperado 6 -> {tb!r}")

        # --- 3. sin session_id NO debe agregar: cuenta 'default' (vacia) ---
        td = s.text(s.call("state_snapshot", {}))
        if verbose: print(f"    sin sid -> {td}")
        cd = num(td, "c")
        if cd != 0:
            fails.append(f"state_snapshot() sin session_id agrega ({cd} cadenas): deberia ser 'default' = 0 -> {td!r}")
        if "[default]" not in td:
            fails.append(f"sin session_id no reporta 'default': {td!r}")

        # --- 4. state_global SI agrega, y lo dice ---
        tg = s.text(s.call("state_global", {}))
        if verbose: print(f"    global -> {tg}")
        if "error" in tg or "<error" in tg:
            fails.append(f"state_global no existe o falla: {tg!r}")
        else:
            if "[global]" not in tg:
                fails.append(f"state_global no marca scope global: {tg!r}")
            cg = num(tg, "c")
            if cg != 7:
                fails.append(f"state_global dice {cg} cadenas, esperado 7 (A:1 + B:6) -> {tg!r}")
            if "sessions" not in tg:
                fails.append(f"state_global no reporta el numero de sesiones: {tg!r}")

        # --- 5. coherencia: la suma de las partes == el global ---
        if not fails:
            if (ca + cb) != cg:
                fails.append(f"partes ({ca}+{cb}={ca+cb}) != global ({cg})")
    finally:
        s.close()

    print(f"tmp: {tmp}")
    if fails:
        print("FAIL")
        for f in fails: print(f"   - {f}")
        return 1
    print("PASS: state_snapshot es por sesion, state_global agrega")
    return 0


if __name__ == "__main__":
    sys.exit(main())
