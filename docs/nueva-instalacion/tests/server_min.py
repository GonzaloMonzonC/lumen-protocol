import sys, json
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
