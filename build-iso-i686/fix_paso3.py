#!/usr/bin/env python3
"""PASO 3: memoria PROPIA del nodo en ^NODO(<id>), sincronizada con el hub.
  - rutina %NM  (R = restaurar al arrancar · S = guardar en el latido)
  - init        -> D ^%NM("R") tras configurar DDP
  - %HB (latido)-> D ^%NM("S")
El nodo SOLO toca su subarbol (^NODO(<id>,...)); con prefijo no trae la de otros.
"""
from pathlib import Path

NM = r'''%NM(OP) ; %NM - MEMORIA PROPIA del nodo: subarbol ^NODO(<id>) sincronizado con el hub
 ; D ^%NM("R") -> RESTAURA su memoria del hub (lo llama el init al arrancar)
 ; D ^%NM("S") -> GUARDA su memoria en el hub (lo llama el latido %HB)
 ; El nodo solo lee/escribe SU subarbol ^NODO(<id>,...): memoria persistente
 ; SIN DISCO (la PDB vive en RAM; el hub guarda la copia duradera).
 N ID
 S ID=$$QUIEN()
 I ID="" W "memoria: sin identidad, no se puede",! Q
 I $G(^CONFIG("ddp_peer"))="" W "memoria: sin hub configurado",! Q
 ; marca de vida: asi siempre hay algo que restaurar y se VE que persiste
 I '$D(^NODO(ID,"memoria","creada")) S ^NODO(ID,"memoria","creada")=$H
 S ^NODO(ID,"memoria","ultima")=$H
 S ^NODO(ID,"memoria","nombre")=$G(^SYS("NODO"))
 I OP="R" D REST Q
 I OP="S" D SAVE Q
 W "uso: D ^%NM(\"R\") restaurar - D ^%NM(\"S\") guardar",!
 Q
QUIEN() ; identidad estable del nodo
 N IDN
 S IDN=$G(^CONFIG("nodo_id"))
 I IDN="" S IDN=$TR($G(^SYS("NODO"))," ./()","-")
 I IDN="" S IDN="nodo-desconocido"
 Q IDN
REST ; trae SU subarbol del hub
 W "memoria: restaurando ",$$QUIEN()," del hub...",!
 W "  ",$DEVICE("ddp:pull","NODO",0,1,$$QUIEN()),!
 I $D(^NODO($$QUIEN(),"memoria","creada")) W "memoria: creada el ",$G(^NODO($$QUIEN(),"memoria","creada")),!
 Q
SAVE ; empuja su memoria al hub
 W "memoria: guardando ",$$QUIEN()," en el hub...",!
 W "  ",$DEVICE("ddp:push","NODO"),!
 Q
'''
p = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines/%NM.m")
p.write_text(NM, encoding="utf-8", newline="")
print("%NM.m escrita")

# init -> restaurar memoria tras configurar DDP
pi = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/init")
s = open(pi, encoding="utf-8", newline="").read()
ancla = '''    echo "[ddp] $_reg"'''
nuevo = '''    echo "[ddp] $_reg"
    # PASO 3 del namespace por nodo: recuperar SU memoria del hub.
    _mem=$(/opt/mvm/mvm-nas -p "$PDB" -r /opt/mvm/routines -e "D ^%NM(\\"R\\")" 2>&1)
    echo "[ddp] $_mem"'''
assert ancla in s, "no encontre el ancla del init"
s = s.replace(ancla, nuevo, 1)
open(pi, "w", encoding="utf-8", newline="").write(s)
print("init OK: restaura memoria al arrancar")

# %HB -> guardar memoria en el latido
ph = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines/%HB.m")
h = open(ph, encoding="utf-8", newline="").read()
ancla_h = '''D ^%DS("TNODO","U")'''
nuevo_h = '''D ^%DS("TNODO","U")
 ; PASO 3: guardar la memoria propia del nodo (^NODO(<id>)) en el hub
 D ^%NM("S")'''
assert ancla_h in h, "no encontre el push del latido"
h = h.replace(ancla_h, nuevo_h, 1)
open(ph, "w", encoding="utf-8", newline="").write(h)
print("%HB OK: guarda memoria en cada latido")
