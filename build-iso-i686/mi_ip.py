#!/usr/bin/env python3
"""IP LAN del PC (donde corre el hub)."""
import re, subprocess

out = subprocess.run(["ipconfig"], capture_output=True).stdout.decode("cp850", "replace")
ips = re.findall(r"IPv4[^:]*:\s*([0-9.]+)", out)
print("IPv4 encontradas:", ips)
for i in ips:
    if i.startswith("192.168.1."):
        print(f"  -> LAN: {i}")
print("\n(el hub escucha en 0.0.0.0:8081; el nodo busca 192.168.1.10 y 192.168.1.14)")
