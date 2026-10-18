#!/usr/bin/env python3
"""test_dos_procesos_no_pierden_cadenas.py — H7

`_pdb_save_all` hace DELETE del namespace STATE completo y lo reescribe con lo
que la INSTANCIA conoce. Habia un merge defensivo para tareas (incidente
task_126) pero NO para cadenas, asunciones, decisiones ni wiki.

Consecuencia: dos procesos abiertos a la vez (Hermes + un script, o Hermes + un
bench) y uno borraba el trabajo del otro. Sin lock, sin error, sin aviso.

Este test arranca DOS servers reales sobre la MISMA PDB temporal, cada uno
escribe su cadena, ambos guardan, y exige que las dos sobrevivan.

Sin dependencias.    python test_dos_procesos_no_pierden_cadenas.py [-v]
"""
import json
import os
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
    """Un proceso server.py por stdio."""

    def __init__(self, think, pdb, tag):
        self.tag = tag
        env = dict(os.environ, PDB_PATH=str(pdb), PYTHONUNBUFFERED="1",
                   PYTHONIOENCODING="utf-8")
        env.pop("LUMEN_THINKING_MAX_CALLS", None)
        self.p = subprocess.Popen([sys.executable, str(think / "server.py")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=env, cwd=str(think),
                                  text=True, encoding="utf-8")
        self.i = 0

    def _send(self, msg):
        self.p.stdin.write(json.dumps(msg) + "\n"); self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError(f"[{self.tag}] server cerro stdout")
        return json.loads(line)

    def init(self):
        self._send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": self.tag, "version": "0"}}})
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method":
                                       "notifications/initialized", "params": {}}) + "\n")
        self.p.stdin.flush()

    def call(self, tool, args):
        self.i += 1
        return self._send({"jsonrpc": "2.0", "id": self.i, "method": "tools/call",
                           "params": {"name": tool, "arguments": args}})

    def text(self, r):
        if "result" in r:
            c = r["result"].get("content") or []
            return c[0].get("text", "") if c else ""
        return f"<err {r.get('error')}>"

    def close(self):
        try:
            self.p.terminate(); self.p.wait(timeout=8)
        except Exception:
            try: self.p.kill()
            except Exception: pass


def cadenas(pdb, think):
    """Lee las cadenas persistidas en la PDB (fuente de verdad).

    Usa pdb_tools.pdb_connect, que crea el esquema si hace falta. Leer con
    sqlite3 directo sobre una PDB recien creada da 'no such table: _globals'.
    """
    import sqlite3
    out = []
    try:
        sys.path.insert(0, str(think.parent / "pdb"))
        import pdb_tools
        conn = pdb_tools.pdb_connect(path=str(pdb))
        for (sk,) in conn.execute(
                "SELECT subkey FROM _globals WHERE ns='STATE'"):
            s = sk.decode("utf-8", "replace") if isinstance(sk, (bytes, bytearray)) else str(sk)
            if ":chain:" in s:
                out.append(s)
        conn.close()
    except Exception as e:
        return [f"<error {e}>"]
    return sorted(out)


def main():
    verbose = "-v" in sys.argv
    think = find_thinking()
    if not (think / "server.py").is_file():
        print(f"SKIP: no encuentro {think}/server.py")
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="h7_2proc_"))
    pdb = tmp / "dos.db"
    print(f"PDB compartida: {pdb}")

    a = Server(think, pdb, "A")
    b = Server(think, pdb, "B")
    fails = []
    try:
        a.init(); b.init()

        # A escribe su cadena (session A)
        a.call("session_init", {"label": "A", "session_id": "sessA"})
        a.call("sequential_thinking", {"thought": "cadena EXCLUSIVA de A",
                                       "nextThoughtNeeded": False, "totalThoughts": 1,
                                       "session_id": "sessA"})
        # B escribe la suya (session B) — distinta sesion, mismo proceso-padre distinto
        b.call("session_init", {"label": "B", "session_id": "sessB"})
        b.call("sequential_thinking", {"thought": "cadena EXCLUSIVA de B",
                                       "nextThoughtNeeded": False, "totalThoughts": 1,
                                       "session_id": "sessB"})

        ta = a.text(a.call("state_snapshot", {"session_id": "sessA"}))
        tb = b.text(b.call("state_snapshot", {"session_id": "sessB"}))
        if verbose:
            print(f"  A ve: {ta}")
            print(f"  B ve: {tb}")

        # Forzar el guardado en AMBOS (session_end hace _save_state + _pdb_save_all)
        a.call("session_end", {"session_id": "sessA"})
        b.call("session_end", {"session_id": "sessB"})
        time.sleep(0.6)

        guardadas = cadenas(pdb, think)
        if verbose:
            print(f"  cadenas en PDB: {guardadas}")

        tiene_a = any("sessA" in s for s in guardadas)
        tiene_b = any("sessB" in s for s in guardadas)
        print(f"  cadena de A persistida: {tiene_a}")
        print(f"  cadena de B persistida: {tiene_b}")

        if not tiene_a:
            fails.append("la cadena de A desaparecio de la PDB (la borro B al guardar)")
        if not tiene_b:
            fails.append("la cadena de B desaparecio de la PDB (la borro A al guardar)")

        # Y tras reiniciar, un tercer proceso debe ver LAS DOS
        a.close(); b.close()
        c = Server(think, pdb, "C")
        try:
            c.init()
            tc = c.text(c.call("session_list", {}))
            if verbose:
                print(f"  C ve tras reinicio: {tc[:200]}")
            if "sessA" not in tc:
                fails.append("tras reiniciar, la sesion A no aparece en session_list")
            if "sessB" not in tc:
                fails.append("tras reiniciar, la sesion B no aparece en session_list")
            print(f"  tercer proceso ve A: {'sessA' in tc} | B: {'sessB' in tc}")
        finally:
            c.close()

        # Snapshots JSON: cada proceso el suyo, sin pisarse
        propios = sorted(p.name for p in tmp.glob("*thinking_state*")) + \
                  sorted(p.name for p in (think).glob(".thinking_state.*"))
        if verbose:
            print(f"  ficheros de estado: {propios}")
    finally:
        try: a.close()
        except Exception: pass
        try: b.close()
        except Exception: pass

    print()
    if fails:
        print(f"FALLO ({len(fails)})")
        for f in fails:
            print(f"   - {f}")
        return 1
    print("PASS: dos procesos no se pisan las cadenas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
