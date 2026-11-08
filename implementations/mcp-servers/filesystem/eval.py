"""
LUMEN Filesystem — Objective Tool Evaluation (9 tools, 28 tests).

El eval original importaba `server_native.py` y llamaba a `process_message()`,
una funcion interna que dejo de existir cuando el server se refactorizo a SHM
(ahora `server_native.py` solo expone `main()` -> ShmNativeServer). El eval
quedaba roto con `AttributeError`.

Se usa el mismo patron que `web/eval.py` y `thinking/eval.py`, que SI pasan:
lanzar `server.py` como SUBPROCESO y hablar JSON-RPC por stdin/stdout. Asi se
prueba el servidor de verdad por su interfaz publica, no una funcion interna
que puede cambiar (o desaparecer) sin avisar.
"""

from __future__ import annotations
import sys, os, json, tempfile, shutil, subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from eval_framework import MCPTestRunner

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'implementations', 'python', 'src'))
sys.path.insert(0, os.path.join(ROOT, 'implementations', 'mcp-servers', 'filesystem'))

runner = MCPTestRunner("FILESYSTEM (9 tools)")

# ── Servidor como subproceso ──
# OJO CON EL ORDEN: ALLOWED_ROOTS lo lee el servidor AL IMPORTAR. Si se define
# despues del Popen, el hijo arranca sin raices permitidas y todas las tools
# devuelven error -> el eval petaba con KeyError 'result' en el primer read_file.
os.environ["ALLOWED_ROOTS"] = tempfile.gettempdir()

python = sys.executable
server_path = os.path.join(os.path.dirname(__file__), 'server.py')
proc = subprocess.Popen(
    [python, "-u", server_path],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True,
)

def rpc(method: str, **params):
    msg = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params:
        msg["params"] = params
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())

def call_tool(name: str, args: dict) -> dict | None:
    return rpc("tools/call", name=name, arguments=args)

# ── Init ──
_ = rpc("initialize", protocolVersion="2025-03-26", capabilities={},
        clientInfo={"name": "eval", "version": "1.0"})

# ── Test data ──
td = tempfile.mkdtemp()
tf = os.path.join(td, "test.txt")
with open(tf, "w") as f:
    f.write("LUMEN EVAL LINE 1\nLINE 2 target\nLINE 3\n" * 5)
os.makedirs(os.path.join(td, "subdir"))
with open(os.path.join(td, "subdir", "nested.txt"), "w") as f:
    f.write("nested content")

# ════════ read_file (5 tests) ════════
r = call_tool("read_file", {"path": tf})
text = r["result"]["content"][0]["text"]
runner.test("read_file", "correctness", lambda: "LUMEN EVAL" in text)
runner.test("read_file", "correctness", lambda: "1|" in text)
runner.test("read_file", "correctness", lambda: len(text.split("\n")) > 5)

r = call_tool("read_file", {"path": tf, "offset": 3, "limit": 2})
runner.test("read_file", "edge-cases", lambda: r and "3|" in r["result"]["content"][0]["text"])

r = call_tool("read_file", {"path": "/nonexistent/xyz.abc"})
runner.test("read_file", "error-handling",
            lambda: r is not None and ("error" in r or "not found" in str(r).lower()))

# ════════ read_files (3 tests) ════════
r = call_tool("read_files", {"paths": [tf, os.path.join(td, "subdir", "nested.txt")]})
runner.test("read_files", "correctness",
            lambda: r and "===" in r["result"]["content"][0]["text"])
runner.test("read_files", "correctness",
            lambda: r and "test.txt" in r["result"]["content"][0]["text"] and "nested.txt" in r["result"]["content"][0]["text"])
r = call_tool("read_files", {"paths": []})
runner.test("read_files", "edge-cases", lambda: r is not None)

# ════════ write_file (3 tests) ════════
wf = os.path.join(td, "write_test.txt")
r = call_tool("write_file", {"path": wf, "content": "Hello LUMEN!"})
runner.test("write_file", "correctness",
            lambda: r and "Wrote" in r["result"]["content"][0]["text"])
runner.test("write_file", "correctness",
            lambda: os.path.exists(wf) and open(wf).read() == "Hello LUMEN!")
r = call_tool("write_file", {"path": wf, "content": "OVERWRITTEN"})
runner.test("write_file", "edge-cases",
            lambda: open(wf).read() == "OVERWRITTEN")

# ════════ search_files (4 tests) ════════
r = call_tool("search_files", {"pattern": "target", "path": td, "target": "content"})
runner.test("search_files", "correctness",
            lambda: r and "test.txt" in r["result"]["content"][0]["text"])
runner.test("search_files", "correctness",
            lambda: r and "LINE 2" in r["result"]["content"][0]["text"])
r = call_tool("search_files", {"pattern": "*.txt", "path": td, "target": "files"})
runner.test("search_files", "edge-cases",
            lambda: r and "test.txt" in r["result"]["content"][0]["text"])
r = call_tool("search_files", {"pattern": "ZZZ_NOMATCH", "path": td, "target": "content"})
runner.test("search_files", "edge-cases", lambda: r is not None)

# ════════ search_with_context (2 tests) ════════
r = call_tool("search_with_context", {"pattern": "target", "path": td, "context": 1})
runner.test("search_with_context", "correctness",
            lambda: r and ">>>" in r["result"]["content"][0]["text"])
runner.test("search_with_context", "correctness",
            lambda: r and "LINE 2" in r["result"]["content"][0]["text"])

# ════════ list_directory (2 tests) ════════
r = call_tool("list_directory", {"path": td})
runner.test("list_directory", "correctness",
            lambda: r and "test.txt" in r["result"]["content"][0]["text"] and "subdir" in r["result"]["content"][0]["text"])
r = call_tool("list_directory", {"path": "/nonexistent_dir"})
runner.test("list_directory", "error-handling",
            lambda: r is not None and ("error" in r or "not found" in str(r).lower()))

# ════════ patch (3 tests) ════════
# Note: patch requires unique match (rejects ambiguous matches)
r = call_tool("patch", {"path": tf, "old_string": "LUMEN EVAL LINE 1", "new_string": "LUMEN PATCHED LINE 1",
                        "replace_all": True})
runner.test("patch", "correctness",
            lambda: r and "result" in r and "error" not in r and
                    "Replaced" in r["result"]["content"][0]["text"],
            "replace_all patch succeeds")
runner.test("patch", "correctness",
            lambda: "LUMEN PATCHED LINE 1" in open(tf).read(), "file modified on disk")
# Ambiguous match without replace_all should be rejected (safety feature)
r = call_tool("patch", {"path": tf, "old_string": "LUMEN", "new_string": "X"})
runner.test("patch", "error-handling",
            lambda: r and "result" in r and ("occurrences" in str(r).lower() or "unique" in str(r).lower()),
            "ambiguous match rejected with guidance")

# ════════ server_stats (2 tests) ════════
r = call_tool("server_stats", {})
runner.test("server_stats", "correctness",
            lambda: r and ("Requests" in str(r) or "Uptime" in str(r) or "operations" in str(r).lower()))
runner.test("server_stats", "correctness",
            lambda: r and "result" in r)

# ════════ stream_read (2 tests) ════════
r = call_tool("stream_read", {"path": tf, "offset": 1, "limit": 3})
runner.test("stream_read", "correctness",
            lambda: r and "content" in r.get("result", {}))
runner.test("stream_read", "edge-cases",
            lambda: r and ("total_lines" in str(r) or "lines" in str(r) or "chunk" in str(r).lower()))

# ════════ SECURITY ════════
r = call_tool("read_file", {"path": "/etc/passwd"})
runner.test("security", "security",
            lambda: r and ("error" in r or "not allowed" in str(r).lower() or "not found" in str(r).lower()))
r = call_tool("read_file", {"path": "../../../etc/passwd"})
runner.test("security", "security",
            lambda: r and ("error" in r or "not allowed" in str(r).lower() or "not found" in str(r).lower()))

shutil.rmtree(td, ignore_errors=True)
print(runner.report())
