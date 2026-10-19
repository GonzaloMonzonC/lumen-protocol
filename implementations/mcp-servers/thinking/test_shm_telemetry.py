"""test_shm_telemetry.py — P0-2 por la vía SHM (la que usa esta máquina).

El test anterior probaba handle_message (camino stdio). Este prueba el QUE SE
USA DE VERDAD: ShmNativeServer ejecuta HANDLERS[tool](args) directamente, así
que sin _telemetry_wrap las llamadas no contaban.
"""
import io
import json
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="shmtel_")
os.environ["PDB_PATH"] = os.path.join(_TMP, "t.db")
os.environ["LUMEN_STATE_DIR"] = os.path.join(_TMP, "state")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server as T  # noqa: E402

OK = 0
FAIL = 0


def check(name, cond, detail=""):
    global OK, FAIL
    if cond:
        OK += 1; print(f"PASA   {name}")
    else:
        FAIL += 1; print(f"FALLA  {name}")
        if detail: print(f"       {detail}")


def main() -> int:
    # Simular EXACTAMENTE lo que hace ShmNativeServer: handler(args) directo
    instrumented = {n: T._telemetry_wrap(n, f) for n, f in T.HANDLERS.items()}
    for i in range(12):
        instrumented["assume"]({"statement": f"s{i}", "confidence": 0.5,
                                "session_id": "default"})

    rep = T._tool_stats_report()
    check("SHM-1 el camino SHM registra llamadas",
          rep.get("assume", {}).get("calls", 0) >= 12,
          f"calls={rep.get('assume', {}).get('calls')}")
    check("SHM-2 p50 presente", isinstance(rep.get("assume", {}).get("p50_ms"), float))

    # error tambien cuenta
    def _boom(args=None):
        raise ValueError("boom")
    instrumented["pattern_record"] = T._telemetry_wrap("pattern_record", _boom)
    try:
        instrumented["pattern_record"]({})
    except ValueError:
        pass
    check("SHM-3 error por camino SHM cuenta",
          T._tool_stats.get("pattern_record", {}).get("errors") == 1,
          f"errors={T._tool_stats.get('pattern_record', {}).get('errors')}")

    # el handler NO se rompe: devuelve lo mismo que el original
    r = instrumented["work_log"]({})
    check("SHM-4 el wrapper no altera el resultado",
          isinstance(r, dict) and "content" in r, f"tipo={type(r)}")

    T._maybe_flush_tool_stats(force=True)
    check("SHM-5 volcado a disco", os.path.exists(T._tool_stats_path()))

    print(f"\n{OK + FAIL} checks · {OK} PASA · {FAIL} FALLA")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
