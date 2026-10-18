#!/usr/bin/env python3
"""Ayudantes del MSM traidos a LUMEN OPS: %UTL (banner) y %PAGE (paginacion).
Convencion del MSM: si $I NO es el principal, NO se pagina (vale para scripts)."""
from pathlib import Path

UTL = r'''%UTL ; AYUDANTE: banner de cabecera + marco (estilo MSM %UTL)
 ; Uso:  D BANNER^%UTL("System Job Status")
 ;       D LINEA^%UTL            <- linea separadora
 ;       W $$ANCHO^%UTL          <- ancho util de la pantalla
 ; Por que existe: en el MSM TODAS las rutinas buenas se apoyan en ayudantes
 ; cortos (%D fecha, %T hora, %UTL banner, %DEVICE paginacion). Sin ellos cada
 ; rutina repite el trabajo y sale precaria.
BANNER(T) ; cabecera: marco + titulo + nodo
 N N S N=$G(^SYS("NODO")) I N="" S N=$G(^SYSINFO("nodo"))
 W !
 W "========== ",T," ==========",!
 I N'="" W "nodo: ",N,!
 W $$LINEA^%UTL
 Q
LINEA() ; linea separadora del ancho util
 N W S W=$$ANCHO^%UTL
 Q $TR($J("",W)," ","-")
ANCHO() ; ancho util: 78 por defecto (cabe en 80 y en el telnet)
 Q 78
'''

PAGE = r'''%PAGE ; AYUDANTE: paginacion (estilo MSM con el protocolo %Q)
 ; Uso:
 ;   S %Q=0                     <- %Q=0 sigue, 1 pausa, 2 salir
 ;   D INI^%PAGE                <- arranca el contador
 ;   ... W lineas ...
 ;   D MAS^%PAGE                <- cada N lineas pregunta "mas?"
 ;   I %Q=2 Q                   <- el que llama decide si sale
 ;   D FIN^%PAGE                <- cierra
 ; CLAVE del MSM: si $I NO es el principal (pipe, script, telnet) NO se pagina:
 ; asi la MISMA rutina sirve para la consola y para un script.
INI ; arranca: decide si se pagina y pone el contador a cero
 S %PG=1,%PN=0
 I '$D(%NOPAGE) S %NOPAGE=0
 ; $I devuelve el dispositivo principal: si no es el nuestro, no paginamos
 I %NOPAGE=1 S %PG=0
 I $I'=$P S %PG=0
 Q:%PG=0
 Q
MAS ; cuenta lineas; al llegar al tope, pausa y pregunta
 I %PG=0 Q
 S %PN=%PN+1
 I (%PN#20)'=0 Q
 W !,"-- mas -- (ENTER sigue, q sale)"
 R %PA:30
 S %PA=$G(%PA)
 I %PA="q"!($E(%PA)="q") S %Q=2 W !,"(salir)",! Q
 S %Q=1
 Q
FIN ; cierra (limpia lo suyo: como hace el EXIT del MSM)
 I %PG=0 K %PG,%PN Q
 K %PG,%PN,%PA
 Q
'''

D = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines")
(D / "%UTL.m").write_text(UTL.replace("\n", "\r\n"), encoding="utf-8", newline="")
(D / "%PAGE.m").write_text(PAGE.replace("\n", "\r\n"), encoding="utf-8", newline="")
print("escritos: %UTL.m y %PAGE.m en deploy/routines/")
for f in ("%UTL.m", "%PAGE.m"):
    t = (D / f).read_text(encoding="utf-8")
    print(f"  {f}: {len(t)} bytes · lineas: {t.count(chr(10))}")
