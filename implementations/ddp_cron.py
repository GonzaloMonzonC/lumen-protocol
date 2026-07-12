#!/usr/bin/env python3
"""ddp_cron.py — Silent DDP sync wrapper for cron jobs.

Solo produce output cuando hay cambios reales.
Sin output = sin novedades = sin mensaje al usuario.
"""
import sys, os

# Añadir el directorio a path
sys.path.insert(0, os.path.expanduser(
    "~/Documents/GitHub/lumen-protocol/implementations"))

from ddp_sync import sync_pull, get_sync_ts, set_sync_ts

import urllib.request, json

EDGE = os.environ.get("EDGE_URL", "https://pdb-edge.gonzalomonzonc.workers.dev")
KEY = os.environ.get("PEDGE_API_KEY", "pdb_dev_2026")
NS = os.environ.get("DDP_NS", "ROUTINE")

def main():
    old_ts = get_sync_ts(NS)
    result = sync_pull(NS)
    new_ts = get_sync_ts(NS)
    
    pulled = result.get("pulled", 0)
    if pulled > 0:
        print(f"🔄 DDP Sync: {pulled} cambios en ^{NS}")
        print(f"   Desde: {old_ts}")
        print(f"   Hasta: {new_ts}")
    # Silencio si no hay cambios

if __name__ == "__main__":
    main()
