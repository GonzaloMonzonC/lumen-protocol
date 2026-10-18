#!/usr/bin/env python3
"""Comprueba el hub DDP local (:8081) — el que busca el init con wget /health."""
import socket, urllib.request

for host in ("127.0.0.1", "192.168.1.10"):
    try:
        s = socket.create_connection((host, 8081), timeout=4)
        s.close()
    except Exception as e:
        print(f"[{host}:8081] TCP cerrado -> {type(e).__name__}")
        continue
    print(f"[{host}:8081] TCP ABIERTO")
    for path in ("/health", "/ddp/health"):
        try:
            r = urllib.request.urlopen(f"http://{host}:8081{path}", timeout=6)
            print(f"   GET {path:14} -> {r.status}  {r.read()[:200].decode('utf-8','replace')}")
        except Exception as e:
            print(f"   GET {path:14} -> {type(e).__name__}: {e}")
