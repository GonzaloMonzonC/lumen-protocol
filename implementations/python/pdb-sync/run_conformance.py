#!/usr/bin/env python3
"""run_conformance.py — Suite de conformidad Spec M-Agent (docs/spec-m-agent.md §9).

Un motor PDB/M-Light es conforme si pasa todas las categorías offline.
Uso:
    python3 run_conformance.py            # solo offline (conformidad)
    python3 run_conformance.py --all      # incluye categorías online
    python3 run_conformance.py lenguaje   # una categoría
"""
import os, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

OFFLINE = {
    "lenguaje": ["tests_stackvm.py", "tests_compiler.py", "tests_compiler_full.py",
                 "tests_bytecode_vm.py", "tests_funcs.py", "tests_for.py",
                 "tests_m_light_errors.py"],
    "imperativos": ["tests_imp01_write.py", "tests_imp02_arith.py",
                    "tests_imp03_global.py", "tests_imp04_do.py",
                    "tests_imp05_for_order.py"],
    "globals": ["tests_type.py", "tests_contains.py", "tests_d6.py", "tests_bij.py"],
    "rutinas": ["tests_routines.py", "tests_mrepl.py"],
    "journal": ["tests_journal.py", "tests_journal_integration.py",
                "tests_journal_daemon.py"],
    "mvm": ["tests_msajob.py", "tests_msasys.py"],
    "contrato": ["tests_contract.py"],
    "integridad": ["tests_integrity.py", "tests_watchdog.py"],
}
ONLINE = {
    "ddp": ["tests_ddp_client.py", "tests_sync_engine.py"],
    "consola": ["tests_console.py", "tests_console_final.py", "tests_logon.py"],
}

RESULT_RE = re.compile(r"(\d+)/(\d+) tests passed")

def run_file(f: Path) -> tuple:
    """→ (passed, total, rc). total=0 si no se pudo parsear."""
    try:
        r = subprocess.run([sys.executable, str(f)], capture_output=True,
                           text=True, timeout=120, cwd=HERE)
    except subprocess.TimeoutExpired:
        return (0, 0, -1)
    m = None
    for m in RESULT_RE.finditer(r.stdout):
        pass  # quedarse con el último
    if m:
        return (int(m.group(1)), int(m.group(2)), r.returncode)
    return (0, 0, r.returncode)

def warmup():
    """Inicializa el schema y siembra el fixture mínimo ^System.

    Varios tests legacy asumen la BD viva del equipo (esperan que
    $O(^System(x)) empiece en "agents", que System(config) tenga hijos,
    ≥5 claves de primer nivel...). Este fixture — espejo mínimo de
    SYSTEM_SCHEMA.md — hace la suite autocontenida en una BD nueva.
    Es idempotente y solo escribe si ^System está vacío."""
    sys.path.insert(0, str(HERE))
    import _paths  # noqa: F401
    from pdb_tools import tool_set, tool_order
    first = tool_order({"ns": "System", "subs": [""]})
    if first.get("value"):
        return  # ya hay datos (BD del equipo) — no tocar
    # Claves de primer nivel que los tests legacy asumen (imp03/05, for,
    # contains, type): "agents" primera, "auto" segunda, "compare" presente,
    # "config" SOLO con hijos ($D=10), "startup" última, ≥10 claves.
    fixture = [
        (["agents", "hermes"], {"rol": "executor", "fixture": True}),
        (["agents", "zalo"], {"rol": "kb", "fixture": True}),
        (["auto", "memory"], {"fixture": True}),
        (["compare", "baseline"], {"fixture": True}),
        (["config", "param"], "value"),
        (["decisions", "001"], {"decision": "fixture", "agente": "conformance"}),
        (["errors"], "no errors (fixture)"),
        (["gobernanza", "reglas", "lectura"], {"*": ["*"]}),
        (["identidad", "hermes"], {"nombre": "Hermes", "fixture": True}),
        (["pulse", "conformance"], {"status": "online"}),
        (["startup", "ts"], "2026-07-14T00:00:00Z"),
    ]
    for subs, value in fixture:
        tool_set({"ns": "System", "subs": subs, "value": value})
    # imp05 recorre ^ROUTINE y espera >10 rutinas registradas
    routine = tool_order({"ns": "ROUTINE", "subs": [""]})
    if not routine.get("value"):
        for i in range(1, 13):
            tool_set({"ns": "ROUTINE", "subs": [f"ZFIX{i:02d}", "src"],
                      "value": "Q  ; conformance fixture"})

def main():
    args = [a for a in sys.argv[1:]]
    try:
        warmup()
    except Exception as e:
        print(f"⚠ warmup falló: {e}")
    cats = dict(OFFLINE)
    if "--all" in args:
        cats.update(ONLINE)
        args.remove("--all")
    if args:
        cats = {k: v for k, v in cats.items() if k in args}
        if not cats:
            print(f"Categoría desconocida. Opciones: {', '.join(list(OFFLINE) + list(ONLINE))}")
            return 2

    print("=" * 60)
    print("🏛  Conformidad Spec M-Agent v0.1")
    print(f"    PDB: {os.environ.get('PDB_PATH', '(default del repo)')}")
    print("=" * 60)

    grand_p = grand_t = failures = 0
    for cat, files in cats.items():
        cp = ct = 0
        missing, broken = [], []
        for name in files:
            f = HERE / name
            if not f.exists():
                missing.append(name)
                continue
            p, t, rc = run_file(f)
            cp += p; ct += t
            if t == 0 or p < t or rc != 0:
                broken.append(f"{name} ({p}/{t}, rc={rc})")
        ok = not broken and not missing
        icon = "✅" if ok else "❌"
        detail = ""
        if broken: detail += " — fallos: " + ", ".join(broken)
        if missing: detail += " — faltan: " + ", ".join(missing)
        print(f"  {icon} {cat:12s} {cp}/{ct}{detail}")
        grand_p += cp; grand_t += ct
        if not ok: failures += 1

    print("-" * 60)
    print(f"📊 TOTAL: {grand_p}/{grand_t} · categorías con fallos: {failures}")
    print("   (conformidad = 0 fallos en categorías offline)")
    return 1 if failures else 0

if __name__ == "__main__":
    sys.exit(main())
