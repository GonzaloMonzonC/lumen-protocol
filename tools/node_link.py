"""node_link.py — enlace HMAC de un nodo LUMEN/Hermes con cadences.app.

Permite a cualquier nodo (PC, Asus, MVM) hablar con cadences.app sin sesión de
navegador: HMAC-SHA256 estilo DDP, el mismo esquema que ya usan poli/thinking.

    firma = hex(HMAC-SHA256(secret, ts + body + secret))

El secreto se lee, por orden:
    1. argumento --key-file
    2. $CADENCES_NODE_KEY
    3. ~/.cadences-node.key   (una línea, modo 600)

Uso:
    python node_link.py ping
    python node_link.py register --node hermes-pc
    python node_link.py --key-file C:/ruta/clave.txt ping

Seguridad: el secreto NUNCA se imprime ni se envía en el cuerpo. Solo se usa
para firmar. La salida muestra únicamente si la firma fue aceptada.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://cadences.app/api/nodes/sync"
UA = "Mozilla/5.0 (compatible; lumen-node-link/1.0)"


def load_key(key_file: str | None = None) -> str:
    """Resuelve el secreto. No lo imprime nunca."""
    if key_file:
        p = pathlib.Path(key_file)
        if not p.exists():
            raise SystemExit(f"No existe el fichero de clave: {p}")
        return p.read_text(encoding="utf-8").strip().splitlines()[0].strip()

    env = os.environ.get("CADENCES_NODE_KEY", "").strip()
    if env:
        return env

    p = pathlib.Path.home() / ".cadences-node.key"
    if p.exists():
        return p.read_text(encoding="utf-8").strip().splitlines()[0].strip()

    raise SystemExit(
        "No hay clave. Opciones:\n"
        "  --key-file <ruta>\n"
        "  export CADENCES_NODE_KEY=...\n"
        f"  escribir {p} (una linea, chmod 600)"
    )


def sign(secret: str, body: str, ts: str) -> str:
    return hmac.new(
        (secret).encode(),
        (ts + body + secret).encode(),
        hashlib.sha256,
    ).hexdigest()


def call(endpoint: str, secret: str, payload: dict, timeout: float = 30.0) -> dict:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    ts = str(int(time.time()))
    sig = sign(secret, body, ts)

    req = urllib.request.Request(
        endpoint,
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-DDP-Timestamp": ts,
            "X-DDP-HMAC": sig,
            "User-Agent": UA,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as x:
            return {"status": x.status, **json.loads(x.read().decode("utf-8", "replace"))}
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            data = {"error": "(sin JSON en la respuesta)"}
        return {"status": e.code, **data}
    except Exception as e:
        return {"status": 0, "error": f"{type(e).__name__}: {e}"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Enlace HMAC nodo <-> cadences.app")
    ap.add_argument("action", choices=["ping", "register"])
    ap.add_argument("--node", default="", help="identidad del nodo (register)")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--key-file", default=None)
    a = ap.parse_args(argv)

    secret = load_key(a.key_file)

    payload = {"action": a.action}
    if a.action == "register":
        if not a.node:
            raise SystemExit("'register' necesita --node <identidad>")
        payload["node"] = a.node

    r = call(a.endpoint, secret, payload)
    ok = bool(r.get("success"))

    # No imprimir nunca el secreto ni la firma.
    if ok:
        print(f"OK   status={r.get('status')} :: {r.get('note') or r.get('pong')}")
        if a.action == "register":
            print(f"     nodo registrado: {r.get('registered')}")
        return 0
    print(f"FALLO status={r.get('status')} :: {r.get('error')}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
