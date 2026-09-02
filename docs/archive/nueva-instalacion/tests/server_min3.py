import sys, json, os, threading, time

_buf = bytearray()
def _reader():
    global _buf
    while True:
        try:
            chunk = os.read(0, 65536)  # ReadFile directo: devuelve lo disponible
        except OSError:
            break
        if not chunk:
            break
        _buf.extend(chunk)
threading.Thread(target=_reader, daemon=True).start()

def readline():
    global _buf
    while b"\n" not in _buf:
        time.sleep(0.01)
    idx = _buf.index(b"\n")
    line = bytes(_buf[:idx])
    del _buf[:idx + 1]
    return line

def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()
while True:
    line = readline()
    if not line:
        break
    try:
        msg = json.loads(line)
        send({"jsonrpc": "2.0", "id": msg.get("id"), "result": {"ok": True}})
    except Exception:
        pass
