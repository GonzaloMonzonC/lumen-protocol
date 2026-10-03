#!/usr/bin/env python3
"""%GUIA - LA GUIA MAESTRA. Un global con las instrucciones de TODO, que:
  (a) se INYECTA en el prompt del LLM  -> deja de inventar
  (b) se VE desde el help              -> misma fuente para el LLM y para el humano
Reglas M-Light: ASCII, sin \\, ayudantes en otra rutina, sin etiquetas de 1 letra.
Estructura:
  ^GUIA("reglas")        las reglas de oro
  ^GUIA("rutinas",X)     que hace la rutina X
  ^GUIA("device",X)      que hace $DEVICE("X")
  ^GUIA("flujo",X)       procedimiento paso a paso
  ^GUIA("error",X)       que significa un error
"""
from pathlib import Path

G = '''%GUIA ; %GUIA - LA GUIA MAESTRA del nodo (para el LLM y para el humano)
 ; Uso:  D ^%GUIA              -> leerla entera (paginada)
 ;       D ZONA^%GUIA("rutinas") -> ver una seccion
 ;       D VER^%GUIA("rutinas","%SS") -> ver una entrada
 ;       D SEMILLA^%GUIA        -> (re)escribir la guia base
 ;       W $$PROMPT^%GUIA       -> el TEXTO para inyectar en el prompt del LLM
 ;
 ; POR QUE EXISTE: el LLM del nodo inventaba porque nadie le daba el estado real.
 ; Aqui vive lo que el nodo SABE HACER, en datos. Se inyecta en su prompt y se
 ; lee desde el help: LA MISMA FUENTE para el LLM y para la persona.
 ;
 N SEC
 D SEMILLA^%GUIA
 I '$D(SEC) S SEC="reglas"
 D INI^%PAGE
 D BANNER^%UTL("GUIA MAESTRA DEL NODO")
 W "Secciones: reglas - rutinas - device - flujo - error",!
 W "Para una seccion:  D ZONA^%GUIA(""rutinas"")",!
 S SEC=""
 F  S SEC=$O(^GUIA(SEC)) Q:SEC=""  I SEC'="reglas" W "  ",SEC," (",$$CUENTA^%GUIA(SEC)," entradas)",!
 D MAS^%PAGE
 D FIN^%PAGE
 Q
 ;
ZONA(SEC) ; lista las entradas de una seccion
 N K,N
 D INI^%PAGE
 D BANNER^%UTL("GUIA: "_SEC)
 S N=0,K=""
 F  S K=$O(^GUIA(SEC,K)) Q:K=""  S N=N+1 W "  ",K,!
 D MAS^%PAGE
 D FIN^%PAGE
 W "(",N," entradas)",!
 Q
 ;
VER(SEC,K) ; lee una entrada
 N I,CL
 D INI^%PAGE
 S CL=SEC_"|"_K
 I '$D(^GUIA(SEC,K)) W "No hay guia para '",K,"' en '",SEC,"'.",! D FIN^%PAGE Q
 D BANNER^%UTL(K)
 S I=0
 F  S I=$O(^GUIA(SEC,K,I)) Q:I=""  D
 . W "  ",$G(^GUIA(SEC,K,I)),!
 . D MAS^%PAGE
 D FIN^%PAGE
 Q
 ;
CUENTA(SEC) ; cuantas entradas tiene una seccion
 N K,N
 S N=0,K=""
 F  S K=$O(^GUIA(SEC,K)) Q:K=""  S N=N+1
 Q N
 ;
PROMPT() ; EL TEXTO QUE SE INYECTA EN EL PROMPT DEL LLM
 N T,SEC,K,CL,I
 D SEMILLA^%GUIA
 S T="=== LO QUE ESTE NODO SABE HACER (guia maestra) ==="_$C(10)
 S SEC=""
 F  S SEC=$O(^GUIA(SEC)) Q:SEC=""  D
 . S T=T_"["_SEC_"]"_$C(10)
 . S K=""
 . F  S K=$O(^GUIA(SEC,K)) Q:K=""  D
 . . S T=T_"  "_K_": "
 . . S I=0,CL=0
 . . F  S I=$O(^GUIA(SEC,K,I)) Q:I=""  D
 . . . I CL>0 S T=T_" - "
 . . . S T=T_$G(^GUIA(SEC,K,I))
 . . . S CL=CL+1
 . . S T=T_$C(10)
 S T=T_"=== REGLA DE ORO: si algo no esta en esta guia, NO lo inventes: dilo. ==="_$C(10)
 S T=T_"=== $DEVICE(...) es una FUNCION (se lee: S R=$DEVICE(""sys:ps"")). NUNCA se hace D $DEVICE(...). ==="_$C(10)
 Q T
 ;
SEMILLA ; escribe la guia base (idempotente: no pisa lo que ya hay)
 D RREGLAS^%GUIA
 D RRUTINAS^%GUIA
 D RDEVICE^%GUIA
 D RFLUJO^%GUIA
 D RERROR^%GUIA
 W:0 ""
 Q
 ;
E(SEC,K,A,B,C) ; escribe una entrada si no existe
 I $D(^GUIA(SEC,K)) Q
 S ^GUIA(SEC,K,1)=A
 I B'="" S ^GUIA(SEC,K,2)=B
 I C'="" S ^GUIA(SEC,K,3)=C
 Q
 ;
RREGLAS ;
 S ^GUIA("reglas",1,1)="1. Si un dato no esta aqui ni en el contexto, DI QUE NO LO SABES. No lo inventes."
 S ^GUIA("reglas",1,2)="2. No inventes rutinas, ni globals, ni $DEVICE que no existan."
 S ^GUIA("reglas",1,3)="3. Antes de tocar un global, miralo con %GL. Antes de volcar, usa el limite."
 S ^GUIA("reglas",1,4)="4. Las credenciales no se muestran ni se escriben en ficheros versionados."
 S ^GUIA("reglas",1,5)="5. El metal manda: si dice una cosa y el codigo otra, gana el metal."
 S ^GUIA("reglas",1,6)="6. $DEVICE(...) es una FUNCION, nunca una orden. Se LEE: S R=$DEVICE(""sys:ps""). NUNCA se hace D $DEVICE(...)."
 S ^GUIA("reglas",1,7)="7. Si la respuesta es una ACCION, una tool o un dato del nodo, LLAMA a la tool; no la describas de memoria."
 Q
 ;
RRUTINAS ;
 D E^%GUIA("rutinas","%SS","estado del sistema: proceso, RAM, red, DDP, jobs, agentes. D ^%SS")
 D E^%GUIA("rutinas","%HELP","ayuda por zonas, se lee del global ^HELP. D ^%HELP")
 D E^%GUIA("rutinas","%GUIA","esta guia, la misma que usa el LLM. D ^%GUIA")
 D E^%GUIA("rutinas","%GL","listado de un global por pantallas: D ^%GL(""NS"",limite)")
 D E^%GUIA("rutinas","%GS","volcar un global como sentencias S (para copiarlo): D ^%GS(""NS"",limite)")
 D E^%GUIA("rutinas","%GD","directorio de globals y rutinas. D ^%GD")
 D E^%GUIA("rutinas","%WIFI","diagnostico de WiFi: capacidad, config y estado. D ^%WIFI")
 D E^%GUIA("rutinas","%NR","registro de nodos: empuja la identidad al hub. D ^%NR")
 D E^%GUIA("rutinas","%NM","memoria propia del nodo (persistente sin disco). D ^%NM")
 D E^%GUIA("rutinas","%CRON","jobs programados del nodo. D ^%CRON")
 D E^%GUIA("rutinas","%HB","latido: avisa al hub de que el nodo vive. D ^%HB")
 D E^%GUIA("rutinas","%AG","agentes enrutados en el nodo. D ^%AG")
 D E^%GUIA("rutinas","%D","fecha de hoy: W $$HOY^%D")
 D E^%GUIA("rutinas","%T","hora actual: W $$AHORA^%T")
 D E^%GUIA("rutinas","%UTL","utilidades compartidas: DIV (division entera) y C2 (dos cifras)")
 D E^%GUIA("rutinas","%PAGE","paginacion: INI, MAS, FIN. Protocolo %Q (0 sigue, 1 pausa, 2 salir)")
 D E^%GUIA("rutinas","%AGENTE","el LLM que LLAMA tools (bucle de tool-calling): W $$CORRE^%AGENTE(PREGUNTA)")
 Q
 ;
RDEVICE ;
 ; OJO: TODAS son FUNCIONES $DEVICE(...) que se LEEN con S. NO son ordenes D.
 D E^%GUIA("device","sys:top","FUNCION: S R=$DEVICE(""sys:top"") -> proceso y sistema: pid, rss, cpu, threads, fds, load, memoria")
 D E^%GUIA("device","sys:ps","FUNCION: S R=$DEVICE(""sys:ps"") -> procesos del OS: pid|comm|rss|estado|ticks. Con R=$DEVICE(""sys:ps"",""10"") los 10 con mas memoria")
 D E^%GUIA("device","sys:mvm","FUNCION: S R=$DEVICE(""sys:mvm"") -> procesos M del motor: fibers/jobs/sesiones (una linea por proceso)")
 D E^%GUIA("device","pdb:","FUNCION: pdb:get, pdb:set, pdb:kill, pdb:order -> la base de datos PROPIA. S R=$DEVICE(""pdb:get"",""NS"",""clave"")")
 D E^%GUIA("device","ddp:","FUNCION: S R=$DEVICE(""ddp:pull"",NS) trae del hub; $DEVICE(""ddp:push"",...) empuja")
 D E^%GUIA("device","http:","FUNCION: peticiones HTTP (para el hub y para las APIs)")
 D E^%GUIA("device","llm:","FUNCION: la puerta de modelos: S R=$DEVICE(""llm:call"",PROMPT,...). Con tools: $DEVICE(""llm:tools"",PROV,MOD,PROMPT,TOOLS_JSON)")
 D E^%GUIA("device","tool:","FUNCION: el catalogo de tools. $DEVICE(""tool:list"") y $DEVICE(""tool:describe"",NOMBRE). Alimenta a %AGENTE")
 D E^%GUIA("device","json:","FUNCION: leer JSON por ruta. $DEVICE(""json:get"",J,""calls[0].name"") y $DEVICE(""json:count"",J,""calls"")")
 D E^%GUIA("device","hw:","FUNCION: hardware: S R=$DEVICE(""hw:disk"") , hw:mem, hw:net, hw:rfkill")
 D E^%GUIA("device","exec:","FUNCION: ejecutar un comando del sistema (con cuidado)")
 Q
 ;
RFLUJO ;
 D E^%GUIA("flujo","UNIR_AL_GRUPO","1. /etc/hub.conf: HUB=<ip> y DDP_KEY=<clave>","2. D ^%NR para registrarse con la identidad firmada","3. D ^%HB y comprobar en el hub con GET /ddp/nodes")
 D E^%GUIA("flujo","CONFIGURAR_WIFI","1. /etc/wifi.conf: SSID, PSK, OCULTA","2. FORZAR=si o ""lumenwifi"" para probarla aunque haya cable","3. D ^%WIFI y mirar /tmp/wpa.log y /tmp/uw.log")
 D E^%GUIA("flujo","GUARDAR_MEMORIA","1. S ^NODO(<id>,""clave"")=<valor>","2. D ^%NM para empujarla al hub","3. Al arrancar, el nodo la recupera solo")
 D E^%GUIA("flujo","LEER_UN_GLOBAL","1. D ^%GL(""NS"",40) para ver el subarbol por pantallas","2. Para copiarlo: D ^%GS(""NS"",80) y pegar en otra MVM")
 D E^%GUIA("flujo","USAR_UNA_TOOL","1. El LLM mira el catalogo con $DEVICE(""tool:list"")","2. Llama la que necesita con $DEVICE(""llm:tools"",...)","3. %AGENTE cierra el bucle: ejecuta la tool y devuelve el resultado al LLM")
 Q
 ;
RERROR ;
 D E^%GUIA("error","PAGINACION","Si sale ""-- mas --"": ENTER sigue, q sale")
 D E^%GUIA("error","DEVICE","Si dice ""Unknown SYS action"": el binario del nodo no tiene esa accion; hay que grabar la ISO nueva")
 D E^%GUIA("error","NOLABEL","Si dice ""unknown label X"": la rutina no esta cargada (el motor carga al arrancar) o la etiqueta es de una sola letra")
 D E^%GUIA("error","PARENTESIS","Si dice ""parentesis desbalanceados"": se ha usado una division rara o un $$LABEL que no resuelve")
 Q
'''

D = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines/%GUIA.m")
D.write_text(G.replace("\n", "\r\n"), encoding="utf-8", newline="")
t = D.read_text(encoding="utf-8")
print(f"escrito: %GUIA.m ({len(t)} bytes)")
print("  no-ASCII:", sum(1 for c in t if ord(c) not in (10, 13) and not (32 <= ord(c) < 127)))
print("  backslash:", chr(92) in t)
print("  entradas:", t.count("D E^%GUIA("))
print("  lineas:", t.count("\n"))
