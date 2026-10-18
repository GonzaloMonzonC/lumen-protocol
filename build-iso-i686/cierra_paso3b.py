#!/usr/bin/env python3
"""%NM v2: en RESTAURAR no tocar la memoria ANTES de traerla (si no, se salta todo)."""
import re
from pathlib import Path

NM = r'''%NM(OP) ; %NM - MEMORIA PROPIA del nodo: subarbol ^NODO(<id>) sincronizado con el hub
 ; D ^%NM("R") -> RESTAURA su memoria del hub (lo llama el init al arrancar)
 ; D ^%NM("S") -> GUARDA su memoria en el hub (lo llama el latido %HB)
 ; El nodo solo lee/escribe SU subarbol ^NODO(<id>,...): memoria persistente
 ; SIN DISCO (la PDB vive en RAM; el hub guarda la copia duradera).
 N ID
 S ID=$$QUIEN^%NM()
 I ID="" W "memoria: sin identidad, no se puede",! Q
 I $G(^CONFIG("ddp_peer"))="" W "memoria: sin hub configurado",! Q
 I OP="R" D REST Q
 I OP="S" D MARCAS D SAVE Q
 W "uso: D ^%NM(\"R\") restaurar - D ^%NM(\"S\") guardar",!
 Q
QUIEN() ; identidad estable del nodo
 N IDN
 S IDN=$G(^CONFIG("nodo_id"))
 I IDN="" S IDN=$TR($G(^SYS("NODO"))," ./()","-")
 I IDN="" S IDN="nodo-desconocido"
 Q IDN
MARCAS ; solo al GUARDAR: sella la memoria para que siempre haya algo que traer
 N ID
 S ID=$$QUIEN^%NM()
 I '$D(^NODO(ID,"memoria","creada")) S ^NODO(ID,"memoria","creada")=$H
 S ^NODO(ID,"memoria","ultima")=$H
 S ^NODO(ID,"memoria","nombre")=$G(^SYS("NODO"))
 Q
REST ; trae SU subarbol del hub (NO escribe nada antes: si no, el pull lo salta)
 N ID
 S ID=$$QUIEN^%NM()
 W "memoria: restaurando ",ID," del hub...",!
 W "  ",$DEVICE("ddp:pull","NODO",0,1,ID),!
 D VER^%NM
 Q
VER ; que ha quedado en la memoria local
 N ID,K
 S ID=$$QUIEN^%NM()
 I '$D(^NODO(ID,"memoria","creada")) W "memoria: no habia nada que recuperar",! Q
 W "memoria: RECUPERADA - creada el ",$G(^NODO(ID,"memoria","creada")),!
 S K="" F  S K=$O(^NODO(ID,"memoria",K)) Q:K=""  W "  ",K," = ",$G(^NODO(ID,"memoria",K)),!
 Q
SAVE ; empuja su memoria al hub
 W "memoria: guardando ",$$QUIEN^%NM()," en el hub...",!
 W "  ",$DEVICE("ddp:push","NODO"),!
 Q
'''
p = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines/%NM.m")
p.write_text(NM.replace("\n", "\r\n"), encoding="utf-8", newline="")
print("%NM v2 escrita (CRLF)")

KEY = re.search(r"^DDP_KEY=(.+)$",
                Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/hub.conf")
                .read_text(encoding="utf-8"), re.M).group(1).strip()

import hashlib, hmac, json, socket, time, urllib.request, urllib.error


def hub_get(path):
    ts = str(int(time.time()))
    sig = hmac.new(KEY.encode(), (ts + path + KEY).encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request("http://127.0.0.1:8081" + path,
                                 headers={"X-DDP-Timestamp": ts, "X-DDP-HMAC": sig})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"http": e.code, "body": e.read().decode()[:150]}
    except Exception as e:
        return {"err": str(e)}


def limpia(b):
    out, i = bytearray(), 0
    while i < len(b):
        if b[i] == 0xFF and i + 2 < len(b):
            i += 3
        else:
            out.append(b[i])
            i += 1
    return bytes(out).decode("utf-8", "replace").replace("\r", "")


class T:
    def __init__(self, h, p, t=45):
        self.s = socket.create_connection((h, p), timeout=t)
        self.s.settimeout(t)

    def leer(self, seg=3.0):
        fin, out = time.time() + seg, b""
        while time.time() < fin:
            try:
                d = self.s.recv(8192)
                if not d:
                    break
                out += d
            except socket.timeout:
                break
        return out

    def manda(self, txt, seg=16.0):
        self.s.sendall(txt.encode() + b"\r\n")
        return self.leer(seg)


c = T("192.168.1.20", 2323)
c.leer(4)
B = "/opt/mvm/mvm-nas -p /tmp/pdb.db -r /opt/mvm/routines -e "
CFG = f'S ^CONFIG("ddp_peer")="http://192.168.1.10:8081" S ^CONFIG("ddp_hmac_key")="{KEY}" '

c.manda("cat > /opt/mvm/routines/%NM.m << 'LUMENEOF'", 3)
for linea in NM.split("\n"):
    c.s.sendall(linea.encode() + b"\r\n")
c.manda("LUMENEOF", 3)
print("%NM v2 copiada al Asus")


def muestra(r):
    return [x.strip() for x in r.split("\n")
            if x.strip() and "[rutina" not in x and B not in x and not x.startswith("/ #")]


def run(m, seg=22):
    for x in muestra(limpia(c.manda(B + "'" + m + "'", seg))):
        print("   ", x)


print("\n=== 0) partir limpio ===")
run(CFG + 'K ^NODO W "borrada",!')

print("\n=== 1) GUARDAR ===")
run(CFG + 'D ^%NM("S")', 30)

print("\n=== 2) el hub guarda el VALOR? (depth=5) ===")
d = hub_get("/ddp/pull?ns=NODO&limit=200&depth=5")
ents = d.get("entries", []) if isinstance(d, dict) else []
mios = [e for e in ents if e.get("subs") and e["subs"][0] == "Asus-1005HA" and e.get("value")]
print(f"    entradas con VALOR bajo Asus-1005HA: {len(mios)}")
for e in mios[:8]:
    print(f"      {e['subs']} = {str(e['value'])[:40]}")

print("\n=== 3) APAGON: borrar local ===")
run(CFG + 'K ^NODO W "borrada",!')
run('W "    $D(^NODO) = ",$D(^NODO),!')

print("\n=== 4) RESTAURAR ===")
run(CFG + 'D ^%NM("R")', 30)
c.s.close()
