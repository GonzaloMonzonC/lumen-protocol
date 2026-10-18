#!/usr/bin/env python3
"""OPCION B (lado HUB): acepta una firma CON IDENTIDAD de nodo, ademas de la legacy.

  legacy -> HMAC(key, ts + body + key)                 (el CIRCULO, sin identidad)
  con ID -> HMAC(key, ts + nodo + body + key)  + X-DDP-Node

Compatibilidad: si NO viene X-DDP-Node, se sigue aceptando la firma legacy -> los
nodos actuales siguen funcionando igual. Pero si VIENE X-DDP-Node, se EXIGE que la
firma de identidad cuadre: un nodo no puede decir "soy otro" sin la clave.
"""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync/vm_api.py"
s = open(P, encoding="utf-8").read()

old = '''def _verify_ddp(body_str, headers):
    """Verify HMAC signature from DDP client. If no key configured, allow local."""
    ts = headers.get("X-DDP-Timestamp", "")
    sig = headers.get("X-DDP-HMAC", "")
    key = os.environ.get("DDP_HMAC_KEY", "")
    if not key:
        return True  # no auth → local-only mode
    msg = (ts + body_str + key).encode()
    expected = hmac.new(key.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)'''

new = '''def _verify_ddp(body_str, headers):
    """Verify HMAC signature from DDP client. If no key configured, allow local.

    DOS ESQUEMAS, COMPATIBLES (opcion B, 2026-10-01):
      · legacy  -> HMAC(key, ts + body + key)              [el CIRCULO, sin identidad]
      · con ID  -> HMAC(key, ts + nodo + body + key)  + cabecera X-DDP-Node

    Compatibilidad: sin X-DDP-Node se acepta la firma legacy, asi los nodos que aun
    no mandan identidad siguen funcionando. PERO si viene X-DDP-Node, se EXIGE que la
    firma con identidad cuadre (no se cae al legacy): asi nadie puede decir "soy otro"
    sin la clave.
    """
    ts = headers.get("X-DDP-Timestamp", "")
    key = os.environ.get("DDP_HMAC_KEY", "")
    if not key:
        return True  # no auth → local-only mode
    nodo = headers.get("X-DDP-Node", "")
    if nodo:
        sig2 = headers.get("X-DDP-HMAC2", "")
        expected2 = hmac.new(key.encode(), (ts + nodo + body_str + key).encode(),
                             hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig2, expected2)
    sig = headers.get("X-DDP-HMAC", "")
    expected = hmac.new(key.encode(), (ts + body_str + key).encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def _ddp_nodo(body_str, headers):
    """ID de nodo VERIFICADO del emisor. '' si no vino identidad o no cuadra la firma.

    Re-verifica por su cuenta (no comparte estado): seguro con ThreadingHTTPServer.
    Llamar DESPUES de que _verify_ddp haya dado True.
    """
    nodo = headers.get("X-DDP-Node", "")
    key = os.environ.get("DDP_HMAC_KEY", "")
    if not (nodo and key):
        return ""
    ts = headers.get("X-DDP-Timestamp", "")
    sig2 = headers.get("X-DDP-HMAC2", "")
    expected = hmac.new(key.encode(), (ts + nodo + body_str + key).encode(),
                        hashlib.sha256).hexdigest()
    return nodo if hmac.compare_digest(sig2, expected) else ""'''

assert old in s, "no encontre _verify_ddp"
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
import py_compile
py_compile.compile(P, doraise=True)
print("PATCH OK: hub acepta firma con identidad (y sigue aceptando la legacy)")
