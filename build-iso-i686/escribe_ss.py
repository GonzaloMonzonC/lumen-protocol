#!/usr/bin/env python3
"""%SS v3 (04-oct-2026): SYSTEM STATUS del nodo - vista tipo MSM.
Cambios de esta version:
  - HDR que dice TODO de un golpe (nodo, version, hora, vivos).
  - LAS DOS LISTAS de procesos (lo que pedia el plan):
      * procesos M del motor  -> $DEVICE("sys:mvm")   (id|estado: RUN/OK/ERR)
      * procesos del OS       -> $DEVICE("sys:ps")    (pid|comm|rss|estado|ticks)
  - $I es alias de $IO (el motor ya lo tiene) -> se usa para saber si hay consola.
Reglas M-Light: ASCII puro, SIN backslash, SIN no-ASCII, sin postcondicionales
dentro de WRITE, $$LABEL entre rutinas, CRLF en el fichero.
"""
from pathlib import Path

SS = r'''%SS(OP) ; %SS ; SYSTEM STATUS del nodo - vista tipo MSM (v3, 04-oct-2026)
 ; Uso:  D ^%SS       -> FOTO completa (para scripts)
 ;       D ^%SS(1)    -> FOTO (igual; el 1 lo pide el plan)
 ;       D ^%SS("M")  -> solo los PROCESOS M del motor
 ;       D ^%SS("P")  -> solo los procesos del OS (top por memoria)
 ; Fuentes VIVAS: $DEVICE("sys:top"), $DEVICE("sys:mvm"), $DEVICE("sys:ps")
 ;              + los globals REALES del nodo. NO usa ^SYSINFO para contar.
 ;
 N OP S OP=$G(OP)
 I OP="M" D PM Q
 I OP="P" D PS Q
 D INI^%PAGE
 D BANNER^%UTL("SYSTEM STATUS")
 D HDR
 D PROCESO
 D SISTEMA
 D MJOBS
 D PSOBS
 D PDBVIVO
 D RED
 D JOBS
 D AGENTES
 D MAS^%PAGE
 D FIN^%PAGE
 Q
 ;
HDR ; el titular: nodo, version, hora y vivos de un golpe
 N N V A NM
 S N=$G(^SYS("NODO")) I N="" S N=$G(^SYSINFO("nodo"))
 S V=$G(^SYS("VERSION")) I V="" S V="?"
 S A=$G(^TNODO("corazon","origen"))
 S NM=$DEVICE("sys:mvm","n")
 W "NODO ..... ",N,"   v",V,!
 I A'="" W "origen ... ",A,!
 W "HORA ..... ",$H,"   ",NM,!
 Q
 ;
PROCESO ; el motor: datos VIVOS de $DEVICE("sys:top")
 N F
 S F=$DEVICE("sys:top")_";"
 W "-- PROCESO (motor) --",!
 W "  pid ...... ",$$V("pid"),"   uptime ",$$V("uptime_s")," s",!
 W "  RSS ...... ",$$V("rss_kb")," KB   pico ",$$V("hwm_kb")," KB",!
 W "  CPU ...... ",$$V("cpu_pct")," %",!
 W "  threads .. ",$$V("threads"),"   fds ",$$V("fds"),!
 Q
 ;
SISTEMA ; el Linux de debajo
 N F
 S F=$DEVICE("sys:top")_";"
 W "-- SISTEMA (Linux) --",!
 W "  RAM ...... ",$$V("mem_avail_kb")," KB libres de ",$$V("mem_total_kb")," KB",!
 W "  load ..... ",$$V("load1")," ",$$V("load5")," ",$$V("load15"),!
 Q
 ;
MJOBS ; LISTA 1: los PROCESOS M del motor ($DEVICE("sys:mvm"))
 N T L
 S T=$DEVICE("sys:mvm")
 W "-- PROCESOS M (motor) --",!
 I T="" W "  (ninguno vivo)",! Q
 F L=1:1:$L(T,$C(10)) D
 . N LN
 . S LN=$P(T,$C(10),L)
 . I LN="" Q
 . W "  ",LN,!
 Q
 ;
PSOBS ; LISTA 2: los PROCESOS DEL OS ($DEVICE("sys:ps"), top por memoria)
 N T L N
 S T=$DEVICE("sys:ps","12")
 W "-- PROCESOS DEL OS (top memoria) --",!
 I T="" W "  (no disponible fuera de Linux)",! Q
 F L=1:1:$L(T,$C(10)) D
 . N LN
 . S LN=$P(T,$C(10),L)
 . I LN="" Q
 . W "  ",LN,!
 Q
 ;
PDBVIVO ; cuenta los globals REALES (en vivo), no el sembrado
 N C
 W "-- PDB (contado en vivo) --",!
 W "  base ..... ",$G(^SYSINFO("pdb")),!
 S C=$$CUENTA("SYS") W "  ^SYS ..... ",C," claves",!
 S C=$$CUENTA("CONFIG") W "  ^CONFIG .. ",C," claves",!
 S C=$$CUENTA("NODOS") W "  ^NODOS ... ",C," nodos registrados",!
 S C=$$CUENTA("NODO") W "  ^NODO .... ",C," nodos con memoria propia",!
 S C=$$CUENTA("TNODO") W "  ^TNODO ... ",C," claves (latido)",!
 S C=$$CUENTA("CRON") W "  ^CRON .... ",C," jobs",!
 S C=$$CUENTA("AGENTES") W "  ^AGENTES . ",C," agentes",!
 S C=$$CUENTA("HELP") W "  ^HELP .... ",C," entradas de ayuda",!
 Q
 ;
CUENTA(NS) ; cuenta en VIVO (SIN indireccion: M-Light puede no tragarla)
 N K,N
 I NS="SYS" S N=0,K="" F  S K=$O(^SYS(K)) Q:K=""  S N=N+1 Q N
 I NS="CONFIG" S N=0,K="" F  S K=$O(^CONFIG(K)) Q:K=""  S N=N+1 Q N
 I NS="NODOS" S N=0,K="" F  S K=$O(^NODOS(K)) Q:K=""  S N=N+1 Q N
 I NS="NODO" S N=0,K="" F  S K=$O(^NODO(K)) Q:K=""  S N=N+1 Q N
 I NS="TNODO" S N=0,K="" F  S K=$O(^TNODO(K)) Q:K=""  S N=N+1 Q N
 I NS="CRON" S N=0,K="" F  S K=$O(^CRON(K)) Q:K=""  S N=N+1 Q N
 I NS="AGENTES" S N=0,K="" F  S K=$O(^AGENTES(K)) Q:K=""  S N=N+1 Q N
 I NS="HELP" S N=0,K="" F  S K=$O(^HELP(K)) Q:K=""  S N=N+1 Q N
 Q 0
 ;
RED ; red y DDP: lo que nos costo tanto
 W "-- RED / DDP --",!
 W "  peer ..... ",$G(^CONFIG("ddp_peer")),!
 W "  wifi ..... red=",$G(^CAPACIDAD("red"))," wifi=",$G(^CAPACIDAD("wifi")),!
 W "  hub ...... ",$G(^CAPACIDAD("hub"))," clave=",$G(^CAPACIDAD("ddp_clave")),!
 Q
 ;
JOBS ; salud / cronica / latido / cron
 W "-- JOBS DEL NODO --",!
 W "  salud .... ",$G(^SALUD(1,"pico_mb"))," MB pico, filas ",$G(^SALUD(1,"filas")),!
 W "  latido ... ",$G(^TNODO("corazon","latido"))," -> hub",!
 I $D(^CRONX("tick")) W "  cron ..... activo @",^CRONX("tick"),!
 E  W "  cron ..... sin arrancar",!
 Q
 ;
AGENTES ; quien anda por aqui
 N N,K
 S N=0,K=""
 F  S K=$O(^AGENTES("routing",K)) Q:K=""  S N=N+1
 W "-- AGENTES --",!
 W "  enrutados ",N," (D ^%AG para la lista)",!
 Q
 ;
PM ; solo los PROCESOS M (para "M")
 D BANNER^%UTL("PROCESOS M")
 D MJOBS
 Q
 ;
PS ; solo los procesos del OS (para "P")
 D BANNER^%UTL("PROCESOS DEL OS")
 D PSOBS
 Q
 ;
V(K) ; valor de "k=" dentro de la cadena de sys:top; "n/d" si no esta
 N T
 S T=$G(F)
 I $P(T,K_"=",1)=T Q "n/d"
 S T=$P(T,K_"=",2)
 Q $P(T,";",1)
'''

D = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines/%SS.m")
D.write_text(SS.replace("\n", "\r\n"), encoding="utf-8", newline="")
t = D.read_text(encoding="utf-8")
print(f"escrito: %SS.m ({D.stat().st_size} bytes)")
print("lineas:", t.count("\n"))
print("no-ASCII:", sum(1 for c in t if ord(c) not in (10, 13) and not (32 <= ord(c) < 127)))
print("backslash:", chr(92) in t)
