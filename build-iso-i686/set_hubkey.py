#!/usr/bin/env python3
"""Escribe lumenos/rootfs/hub.conf con la clave HMAC del hub DDP.
NO imprime la clave. hub.conf esta GITIGNORED (lumenos/.gitignore)."""
import os, re

RAIZ = "C:/Users/gonzalo/Documents/GitHub/mvm-nas"
origen = f"{RAIZ}/f2c-test.db"
d = open(origen, "rb").read()
m = re.search(rb'ddp_hmac_key[^\x00]{0,4}([0-9a-fA-F]{64})', d)
assert m, "no encontre la clave"
clave = m.group(1).decode()

destino = f"{RAIZ}/lumenos/rootfs/hub.conf"
contenido = f"""# hub.conf — credencial del HUB DDP del circulo (NO SE VERSIONA)
# El hub vive en 192.168.1.10:8081 (vm_api). Clave HMAC compartida.
# Formato: DDP_KEY=<hex de 64>   · sin comillas, sin espacios alrededor del '='
DDP_KEY={clave}
"""
with open(destino, "w", newline="\n", encoding="utf-8") as f:
    f.write(contenido)
os.chmod(destino, 0o600)

print(f"escrito: {destino}")
print(f"  clave {clave[:6]}...{clave[-4:]} ({len(clave)} chars) · fichero {os.path.getsize(destino)} bytes")

# comprobar que git lo ignora
import subprocess
r = subprocess.run(["git", "check-ignore", "-v", "lumenos/rootfs/hub.conf"],
                   cwd=RAIZ, capture_output=True, text=True)
print("  git:", r.stdout.strip() or "⚠️ NO IGNORADO")
