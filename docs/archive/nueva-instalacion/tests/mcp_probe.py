#!/usr/bin/env python3
"""mcp_probe.py — cliente MCP stdio de prueba para el benchmark de la nueva instalación.

Lanza un server MCP (igual que Hermes) y ejecuta tools/list + tools/call.
Reproduce el entorno exacto del proceso MCP para diagnosticar fallos que
solo aparecen dentro del proceso (cwd, env, sys.path).

Uso:
    python mcp_probe.py <server.py> <tool_name> <json_args>
Ej:
    python mcp_probe.py ../../mcp-servers/thinking/server.py checklist '{"action":"get","task_type":"research"}'
"""
import json
import subprocess
import sys
import time

def main():
    server_script = sys.argv[1]
    tool_name = sys.argv[2]
    args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}

    proc = subprocess.Popen(
        # -u: sin buffering en stdin/stdout (pipes de Windows bloquean readline)
        [sys.executable, "-u", server_script],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    def send(msg: dict) -> None:
        # MCP estándar: framing Content-Length
        data = json.dumps(msg).encode("utf-8")
        proc.stdin.write(f"Content-Length: {len(data)}\r\n\r\n".encode() + data)
        proc.stdin.flush()

    # Reader único (ReadFile nativo: devuelve lo disponible, sin bloqueo 8KB)
    import ctypes
    import msvcrt
    import threading
    _k32 = ctypes.windll.kernel32
    _h = msvcrt.get_osfhandle(proc.stdout.fileno())
    _buf = bytearray()
    _stop_reader = threading.Event()

    def _reader():
        while not _stop_reader.is_set():
            try:
                cbuf = ctypes.create_string_buffer(8192)
                n = ctypes.c_ulong(0)
                ok = _k32.ReadFile(_h, cbuf, 8192, ctypes.byref(n), None)
                if not ok or n.value == 0:
                    break
                _buf.extend(cbuf.raw[:n.value])
            except Exception:
                break

    threading.Thread(target=_reader, daemon=True).start()

    def recv(timeout: float = 15.0) -> dict:
        """Lee un mensaje MCP Content-Length del buffer compartido."""
        end = time.time() + timeout
        while time.time() < end:
            while b"\r\n\r\n" in _buf:
                header, rest = bytes(_buf).split(b"\r\n\r\n", 1)
                m = [l for l in header.decode(errors="replace").split("\r\n")
                     if l.lower().startswith("content-length")]
                if not m:
                    del _buf[:len(header) + 4]
                    continue
                length = int(m[0].split(":")[1].strip())
                if len(rest) >= length:
                    body = rest[:length]
                    del _buf[:len(header) + 4 + length]
                    return json.loads(body)
            time.sleep(0.1)
        _stop_reader.set()
        raise TimeoutError(f"timeout esperando respuesta (buf={bytes(_buf)[:200]!r})")

    try:
        time.sleep(2.5)  # el server tarda en arrancar (imports + _load_state)
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                         "clientInfo": {"name": "mcp-probe", "version": "1.0"}}})
        init = recv(30)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        time.sleep(0.3)
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = recv()
        n_tools = len(tools.get("result", {}).get("tools", []))
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": tool_name, "arguments": args}})
        call = recv()
        print(f"INIT: {init.get('result', {}).get('serverInfo')}")
        print(f"TOOLS: {n_tools}")
        print(f"CALL {tool_name}:")
        print(json.dumps(call, ensure_ascii=False, indent=2)[:3000])
    finally:
        proc.terminate()
        time.sleep(0.5)
        err = proc.stderr.read().decode("utf-8", "replace")
        if err.strip():
            print("\n--- STDERR del server (últimas 30 líneas) ---")
            print("\n".join(err.strip().splitlines()[-30:]))

if __name__ == "__main__":
    main()
