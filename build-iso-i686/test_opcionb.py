#!/usr/bin/env python3
"""Prueba la logica de _verify_ddp / _ddp_nodo (opcion B) sin levantar servidor."""
import hashlib, hmac, importlib.util, os, sys, time

os.environ["DDP_HMAC_KEY"] = "clave_de_prueba_para_el_test_0123456789abcdef"

P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync/vm_api.py"
sys.path.insert(0, "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync")
spec = importlib.util.spec_from_file_location("vmapi_test", P)
m = importlib.util.module_from_spec(spec)
sys.modules["vmapi_test"] = m
# importar el modulo ejecuta su nivel superior; si algo falla lo veremos
spec.loader.exec_module(m)

KEY = os.environ["DDP_HMAC_KEY"]
ts = str(int(time.time()))
BODY = "/ddp/pull?ns=SYS"

legacy = hmac.new(KEY.encode(), (ts + BODY + KEY).encode(), hashlib.sha256).hexdigest()
NODO = "Asus-1005HA-a1b2c3"
sig_id = hmac.new(KEY.encode(), (ts + NODO + BODY + KEY).encode(), hashlib.sha256).hexdigest()
sig_id_malo = hmac.new("otra_clave".encode(), (ts + NODO + BODY + "otra_clave").encode(),
                       hashlib.sha256).hexdigest()

casos = [
    ("legacy correcta (nodo actual)",
     {"X-DDP-Timestamp": ts, "X-DDP-HMAC": legacy}, True, ""),
    ("legacy FALSIFICADA",
     {"X-DDP-Timestamp": ts, "X-DDP-HMAC": "00" * 32}, False, ""),
    ("identidad correcta (nodo nuevo)",
     {"X-DDP-Timestamp": ts, "X-DDP-Node": NODO, "X-DDP-HMAC2": sig_id}, True, NODO),
    ("identidad FALSIFICADA (clave distinta)",
     {"X-DDP-Timestamp": ts, "X-DDP-Node": NODO, "X-DDP-HMAC2": sig_id_malo}, False, ""),
    ("dice ser otro nodo, firma del primero (suplantacion)",
     {"X-DDP-Timestamp": ts, "X-DDP-Node": "Acer-TravelMate", "X-DDP-HMAC2": sig_id}, False, ""),
    ("trae X-DDP-Node pero SIN HMAC2 (no vale caer al legacy)",
     {"X-DDP-Timestamp": ts, "X-DDP-Node": NODO, "X-DDP-HMAC": legacy}, False, ""),
]

print(f"{'CASO':<52} {'verify':<7} {'nodo':<20} esperado")
print("-" * 95)
ok = True
for nombre, hdrs, esp_v, esp_n in casos:
    v = m._verify_ddp(BODY, hdrs)
    n = m._ddp_nodo(BODY, hdrs) if v else ""
    bien = (v == esp_v and n == esp_n)
    ok = ok and bien
    print(f"{nombre:<52} {str(v):<7} {n or '-':<20} {'OK' if bien else 'MAL'}")
print("-" * 95)
print("TODOS LOS CASOS:", "OK ✅" if ok else "HAY FALLOS ❌")
