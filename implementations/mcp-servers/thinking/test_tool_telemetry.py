"""test_tool_telemetry.py — criterio de aceptación de P0-2 (sin pytest).

La instrumentación vive en el dispatch `tools/call` (un punto único que cubre
las 89 handlers), así que se prueba POR AHÍ (JSON-RPC), no llamando handlers
sueltos: llamar al handler directo salta la telemetría por diseño.
"""
import io
import json
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="telemetry_")
os.environ["PDB_PATH"] = os.path.join(_TMP, "t.db")
os.environ["LUMEN_STATE_DIR"] = os.path.join(_TMP, "state")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # lumen_mcp_stdio

import server as T  # noqa: E402

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


def call(tool, args=None):
    """Ejecuta una tool por la vía REAL (dispatch tools/call) capturando la salida."""
    class _Buf(io.StringIO):
        def __init__(self):
            super().__init__()
            self.buffer = io.BytesIO()

    buf = _Buf()
    stdout_real, stderr_real = sys.stdout, sys.stderr
    sys.stdout = buf
    sys.stderr = io.StringIO()
    try:
        T.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": args or {"session_id": "default"}},
        })
    finally:
        sys.stdout, sys.stderr = stdout_real, stderr_real
    return buf.getvalue() or buf.buffer.getvalue().decode("utf-8", "replace")


def main() -> int:
    # 10 llamadas por el dispatch real
    for i in range(10):
        call("assume", {"statement": f"s{i}", "confidence": 0.5, "session_id": "default"})

    rep = T._tool_stats_report()
    st = rep.get("assume", {})
    check("P0-2a telemetria registra llamadas", st.get("calls", 0) >= 10,
          f"calls={st.get('calls')}")
    check("P0-2b p50 calculado", isinstance(st.get("p50_ms"), float),
          f"p50={st.get('p50_ms')}")

    nunca = [t for t in T.HANDLERS if t not in T._tool_stats]
    check("P0-2c tool nunca llamada NO tiene p50 (null != 0)",
          "pattern_record" not in rep and "pattern_record" in nunca,
          f"en reporte={'pattern_record' in rep}, en nunca={'pattern_record' in nunca}")
    check("P0-2d toda tool con calls>0 tiene p50",
          all(v["p50_ms"] is not None for v in rep.values() if v["calls"] > 0))

    T._maybe_flush_tool_stats(force=True)
    path = T._tool_stats_path()
    check("P0-2e fichero escrito", os.path.exists(path), path)

    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    check("P1-5  fichero FUERA del repo",
          not path.replace("\\", "/").startswith(repo.replace("\\", "/")), path)

    T._tool_stats.clear()
    T._load_tool_stats()
    rep2 = T._tool_stats_report()
    check("P0-2f sobrevive a reinicio (recarga)",
          rep2.get("assume", {}).get("calls", 0) >= 10,
          f"tras recarga calls={rep2.get('assume', {}).get('calls')}")

    antes = T._tool_stats.get("work_done", {}).get("errors", 0)
    T._record_tool("work_done", 1.0, False)
    check("P0-2g cuenta errores", T._tool_stats["work_done"]["errors"] == antes + 1)

    # server_stats expone el desglose
    call("server_stats", {"session_id": "default"})
    check("P0-2h server_stats tool registrada", "server_stats" in T._tool_stats)

    print(f"\n{OK + FAIL} checks · {OK} PASA · {FAIL} FALLA")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
