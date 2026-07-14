#!/usr/bin/env python3
"""tests_contract.py — Guard del contrato PDB (Fase 1b).

Regla 1: prohibido sqlite3.connect() fuera de pdb_tools.py / thinking/_pdb.py.
Regla 2: prohibidas rutas hardcodeadas ~/Documents/GitHub o C:/Users.

Exentos: bench/, tests/, y scripts one-off (test*, debug_*, fix_*, replace_*).
La lista de exentos solo puede ENCOGER (ratchet) — ver docs/PLAN_EVOLUCION.md §2.1.
"""
import sys
from pathlib import Path

import _paths

IMPL = _paths.REPO / "implementations"

# Únicos ficheros con derecho a abrir SQLite del PDB
CONNECT_ALLOWED = {
    "implementations/mcp-servers/pdb/pdb_tools.py",
    "implementations/mcp-servers/thinking/_pdb.py",  # solo docstring + reexport
}

EXEMPT_DIRS = ("/bench/", "/tests/")
EXEMPT_PREFIXES = ("test", "debug_", "fix_", "replace_", "_fix_")
# Legacy con rutas viejas en docstrings/usage, sin efecto en runtime
PATH_EXEMPT_FILES = {"pdb_docs_git_hook.py"}

p = 0
fail = 0

def t(name, ok, detail=""):
    global p, fail
    if ok:
        p += 1
        print(f"  ✅ {name}")
    else:
        fail += 1
        print(f"  ❌ {name}{' — ' + detail if detail else ''}")

def exempt(f: Path) -> bool:
    rel = f.as_posix()
    if any(d in rel for d in EXEMPT_DIRS):
        return True
    return f.name.startswith(EXEMPT_PREFIXES)

print("=" * 55)
print("🛡  Contrato PDB — guard (Fase 1b)")
print("=" * 55)

connect_violations = []
path_violations = []
for f in sorted(IMPL.rglob("*.py")):
    rel = f.relative_to(_paths.REPO).as_posix()
    try:
        src = f.read_text(encoding="utf-8")
    except Exception:
        continue
    if "sqlite3.connect" in src and rel not in CONNECT_ALLOWED and not exempt(f):
        connect_violations.append(rel)
    if ("Documents/GitHub" in src or "C:/Users" in src) and not exempt(f) \
            and f.name not in PATH_EXEMPT_FILES:
        path_violations.append(rel)

t("sqlite3.connect solo en pdb_tools/_pdb",
  not connect_violations, ", ".join(connect_violations))
t("sin rutas hardcodeadas (Documents/GitHub, C:/Users)",
  not path_violations, ", ".join(path_violations))

# pdb_connect funciona y respeta el contrato
try:
    from pdb_tools import pdb_connect
    c = pdb_connect()
    mode = c.execute("PRAGMA journal_mode").fetchone()[0]
    t("pdb_connect() abre en WAL", mode == "wal", f"mode={mode}")
    c.close()
    r = pdb_connect(readonly=True)
    qo = r.execute("PRAGMA query_only").fetchone()[0]
    t("pdb_connect(readonly=True) es query_only", qo in (1, "1"), f"query_only={qo}")
    try:
        r.execute("INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES ('X', x'00', x'00')")
        t("readonly rechaza escrituras", False)
    except Exception:
        t("readonly rechaza escrituras", True)
    r.close()
except Exception as e:
    t("pdb_connect importable", False, str(e))

print(f"\n📊 {p}/{p + fail} tests passed")
sys.exit(1 if fail else 0)
