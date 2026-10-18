#!/usr/bin/env python3
"""PASOS 1+2 del namespace por nodo:
  1) Nodo: rutina %NR (registro) + el init la llama al arrancar -> ^NODOS(<id>,...)
  2) Hub:  endpoint GET /ddp/nodes -> lista de nodos vivos
"""
import py_compile, re
from pathlib import Path

# ─────────── 1a) RUTINA %NR (registro del nodo) ───────────
NR = r'''%NR(IP) ; %NR - Registro del NODO en el ecosistema (namespace ^NODOS)
 ; D ^%NR("192.168.1.20")  -> escribe ^NODOS(<id>,...) y lo EMPUJA al hub.
 ; Lo llama el init al arrancar. Tambien vale como LATIDO (actualiza "ultima").
 ; ID: ^CONFIG("nodo_id") manda; si no, el nombre del DMI ^SYS("NODO") saneado.
 N ID,TS
 S ID=$G(^CONFIG("nodo_id"))
 I ID="" S ID=$TR($G(^SYS("NODO"))," ./()","-")
 I ID="" S ID="nodo-desconocido"
 S TS=$H
 I '$D(^NODOS(ID,"primera")) S ^NODOS(ID,"primera")=TS
 S ^NODOS(ID,"nombre")=$G(^SYS("NODO"))
 S ^NODOS(ID,"id")=ID
 I $G(IP)'="" S ^NODOS(ID,"ip")=$G(IP)
 I $G(^CAPACIDAD("ram_mb"))'="" S ^NODOS(ID,"ram_mb")=$G(^CAPACIDAD("ram_mb"))
 I $G(^CAPACIDAD("cpu"))'="" S ^NODOS(ID,"cpu")=$G(^CAPACIDAD("cpu"))
 I $G(^CAPACIDAD("virt"))'="" S ^NODOS(ID,"virt")=$G(^CAPACIDAD("virt"))
 S ^NODOS(ID,"ultima")=TS
 W "registrado: ",ID,I $G(IP)'="" " ("_$G(IP)_")",!
 I $G(^CONFIG("ddp_peer"))="" W "sin hub: no se envia",! Q
 W "hub: ",$DEVICE("ddp:push","NODOS"),!
 Q
'''
p_nr = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines/%NR.m")
p_nr.write_text(NR, encoding="utf-8", newline="")
print(f"escrita {p_nr.name} ({len(NR)} bytes)")

# ─────────── 1b) EL INIT LLAMA A %NR ───────────
p_init = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/init")
s = open(p_init, encoding="utf-8", newline="").read()
ancla = '''    echo "[ddp] nodo configurado para hablar DDP (peer + clave)"'''
nuevo = '''    echo "[ddp] nodo configurado para hablar DDP (peer + clave)"
    # PASO 1 del namespace por nodo: registrarse en ^NODOS y empujarlo al hub.
    _reg=$(/opt/mvm/mvm-nas -p "$PDB" -r /opt/mvm/routines -e "D ^%NR(\\"$IP\\")" 2>&1)
    echo "[ddp] $_reg"'''
assert ancla in s, "no encontre el ancla del init"
s = s.replace(ancla, nuevo, 1)
p_init.write_text(s, encoding="utf-8", newline="")
print("init OK: llama a %NR con la IP del nodo")

# ─────────── 2) HUB: /ddp/nodes ───────────
p_vm = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync/vm_api.py")
v = open(p_vm, encoding="utf-8", newline="").read()

ruta_old = '''        elif path == "/ddp/pull":
            self._handle_ddp_pull(qs)'''
ruta_new = '''        elif path == "/ddp/pull":
            self._handle_ddp_pull(qs)
        elif path == "/ddp/nodes":
            self._handle_ddp_nodes(qs)'''
assert ruta_old in v, "no encontre la ruta /ddp/pull"
v = v.replace(ruta_old, ruta_new, 1)

h_old = '''    def _handle_ddp_raw(self, qs):'''
h_new = '''    def _handle_ddp_nodes(self, qs):
        """GET /ddp/nodes — registro de NODOS del ecosistema (namespace NODOS).

        Los nodos lo escriben al arrancar (rutina %NR) y lo empujan al hub:
            ^NODOS(<id>,"nombre"|"ip"|"version"|"primera"|"ultima"|...)
        Con esto, cualquier nodo o la web pueden ver QUIEN esta vivo.
        """
        try:
            raw = self.path
            if not _verify_ddp(raw, self.headers):
                self._json({"error": "HMAC auth failed"}, 403)
                return
            quien = _ddp_nodo(raw, self.headers)
            r = _ddp_pull("NODOS", None, int(qs.get("limit", "2000")), 0, 1)
            nodos = {}
            for e in r.get("entries", []):
                subs = e.get("subs") or []
                if len(subs) >= 2 and e.get("value") is not None:
                    nodos.setdefault(str(subs[0]), {})[str(subs[1])] = e["value"]
            self._json({"ok": True, "pide": quien or None,
                        "n": len(nodos), "nodos": nodos})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_ddp_raw(self, qs):'''
assert h_old in v, "no encontre _handle_ddp_raw"
v = v.replace(h_old, h_new, 1)

p_vm.write_text(v, encoding="utf-8", newline="")
py_compile.compile(str(p_vm), doraise=True)
print("hub OK: ruta /ddp/nodes + handler (compila)")
