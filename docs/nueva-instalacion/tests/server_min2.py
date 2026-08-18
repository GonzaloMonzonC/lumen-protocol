import sys, json, os
# stdin con line-buffering: evita el bloqueo de 8KB del read() en pipes Windows
if sys.stdin and sys.stdin.buffer:
    sys.stdin = os.fdopen(sys.stdin.fileno(), "r", encoding="utf-8", buffering=1)
def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()
while True:
    line = sys.stdin.readline()
    if not line:
        break
    try:
        msg = json.loads(line)
        send({"jsonrpc": "2.0", "id": msg.get("id"), "result": {"ok": True}})
    except Exception:
        pass
