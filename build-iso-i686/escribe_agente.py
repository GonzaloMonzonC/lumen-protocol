#!/usr/bin/env python3
"""%AGENTE (04-oct-2026, v2) — EL BUCLE DE TOOL-CALLING en M (DISENO-4).
El LLM del nodo deja de inventar: se le da el CATALOGO de tools (^TOOLS) y el LLM
LLAMA la que necesita. El bucle vive en M (no en Rust) para TRAZABILIDAD (^AGLOG).

v2 (correccion tras revision): usa el PROTOCOLO CORRECTO de tool-calling —
se mantiene el historial de mensajes (user -> assistant(tool_calls) -> tool(res))
y $DEVICE("llm:tools") recibe ese historial, no un prompt concatenado. Asi el
modelo no repite la misma tool en bucle ni alucina sobre los resultados.

COMO SE EJECUTA UNA TOOL (verificado, sin indireccion):
  - Devices (sys:ps, sys:mvm, ...) -> devuelven string directo.
  - Rutinas M que IMPRIMEN (%SS, %GD...) -> $DEVICE("spawn:run","D ^%RTN",15)
    devuelve "exit=0<NL><salida>". (spawn relanza el nodo: caro, pero aislado.)

Reglas M-Light: ASCII puro, SIN backslash, SIN no-ASCII, CRLF en el fichero.
"""
from pathlib import Path

AG = r'''%AGENTE ; %AGENTE ; el LLM que LLAMA tools (bucle de tool-calling v2, DISENO-4)
 ; Uso:  W $$CORRE^%AGENTE(PREGUNTA)             -> respuesta final (texto)
 ;       W $$CORRE^%AGENTE(PREGUNTA,"g:TOOLS")   -> catalogo del global ^TOOLS
 ;       D ^%AGENTE                              -> demo interactiva
 ;       D TOOLS^%AGENTE                         -> escribir el catalogo base
 ;
CORRE(P,TREF,MX) ; el bucle: pregunta P, catalogo TREF, tope de vueltas MX
 N VUE,TXT,JS,KIND,NT,I,TN,TA,TR,TOOLS,PROV,MOD,HIST
 S TREF=$G(TREF,"g:TOOLS")
 S MX=$G(MX,6)
 S PROV=$G(^CONFIG("agente_prov"),"deepseek")
 S MOD=$G(^CONFIG("agente_modelo"),"deepseek-flash")
 S TOOLS=$$CATALOGO(TREF)
 I TOOLS="[]" Q "no hay catalogo de tools (^TOOLS vacio)"
 ; historial de mensajes (protocolo tool-calling): empieza con el usuario
 S HIST="[{""role"":""user"",""content"":"""_$$ESC(P)_"""}]"
 S TXT="",VUE=0
 F  Q:VUE>=MX  D
 . S VUE=VUE+1
 . S JS=$DEVICE("llm:tools",PROV,MOD,"",TOOLS,"",HIST)
 . S KIND=$DEVICE("json:get",JS,"kind")
 . I KIND="text" S TXT=$DEVICE("json:get",JS,"content") S VUE=MX Q
 . I KIND="err" S TXT="[error LLM: "_$DEVICE("json:get",JS,"msg")_"]" S VUE=MX Q
 . I KIND'="tool" S VUE=MX Q
 . ; anadir la respuesta del asistente (con sus tool_calls) al historial
 . S HIST=$$QUITAFIN(HIST)_","_$$ASST(JS)
 . S NT=$DEVICE("json:count",JS,"calls")
 . S I=0
 . F  Q:I>=NT  D
 . . S TN=$DEVICE("json:get",JS,"calls["_I_"].name")
 . . S TA=$DEVICE("json:get",JS,"calls["_I_"].args")
 . . S TID=$DEVICE("json:get",JS,"calls["_I_"].id")
 . . S TR=$$EJECUTA(TN,TA)
 . . S ^AGLOG($H,VUE,I)=TN_" -> "_$E(TR,1,300)
 . . ; anadir el mensaje role=tool con su tool_call_id y el resultado
 . . S HIST=HIST_",{""role"":""tool"",""tool_call_id"":"""_$$ESC(TID)_""",""content"":"""_$$ESC($E(TR,1,2000))_"""}"
 . . S I=I+1
 Q $G(TXT)
 ;
CATALOGO(TREF) ; resuelve la referencia al catalogo -> JSON de tools (formato OpenAI)
 N LIST,L,N,JSON,SCHEMA,NOM
 S LIST=$DEVICE("tool:list",TREF)
 I LIST="" Q "[]"
 I $E(LIST,1,4)="ERR:" Q "[]"   ; referencia no resoluble: sin catalogo (no rompe)
 S JSON="[",N=0
 F L=1:1:$L(LIST,$C(10)) D
 . S NOM=$P($P(LIST,$C(10),L),"|",1)
 . I NOM="" Q
 . S SCHEMA=$DEVICE("tool:describe",NOM,TREF)
 . I SCHEMA="" Q
 . I N>0 S JSON=JSON_","
 . S JSON=JSON_SCHEMA
 . S N=N+1
 Q JSON_"]"
 ;
ASST(JS) ; construye el mensaje assistant con sus tool_calls (para el historial)
 N NT,I,TC,TN,TA,ID,OUT
 S NT=$DEVICE("json:count",JS,"calls")
 S TC=""
 S I=0
 F  Q:I>=NT  D
 . S TN=$DEVICE("json:get",JS,"calls["_I_"].name")
 . S TA=$DEVICE("json:get",JS,"calls["_I_"].args")
 . S ID=$DEVICE("json:get",JS,"calls["_I_"].id")
 . I I>0 S TC=TC_","
 . S TC=TC_"{""id"":"""_$$ESC(ID)_""",""type"":""function"",""function"":{""name"":"""_TN_""",""arguments"":"""_$$ESC(TA)_"""}}"
 . S I=I+1
 S OUT="{""role"":""assistant"",""content"":null,""tool_calls"":["_TC_"]}"
 Q OUT
 ;
QUITAFIN(H) ; quita el ']' final del array JSON de historial (para anadir mas)
 Q $E(H,1,$L(H)-1)
 ;
ESC(S) ; escapa un string para meterlo dentro de un JSON SIN usar backslash
 ; (el backslash rompe el parseo M-Light: es la leccion del 03-oct). En JSON,
 ; la comilla se escapa con $C(92)_$C(34) - que en el FICHERO es puro M, sin
 ; escribir el caracter backslash literal. Los saltos de linea se vuelven espacio.
 N R,I,C
 S S=$G(S),R=""
 F I=1:1:$L(S) D
 . S C=$E(S,I)
 . I C="""" S R=R_$C(92)_$C(34) Q
 . I C=$C(10) S R=R_" " Q
 . I C=$C(13) Q
 . I C=$C(9) S R=R_" " Q
 . S R=R_C
 Q R
 ;
EJECUTA(TN,TA) ; ejecuta la tool TN con argumentos TA (JSON) -> resultado (texto)
 I TN="sys:top" Q $DEVICE("sys:top")
 I TN="sys:ps" Q $DEVICE("sys:ps","10")
 I TN="sys:mvm" Q $DEVICE("sys:mvm")
 I TN="audio:info" Q $DEVICE("audio:info")
 I TN="cam:list" Q $DEVICE("cam:list")
 I TN="%SS" Q $$CAPTURA("D ^%SS")
 I TN="%GD" Q $$CAPTURA("D ^%GD")
 I TN="%WIFI" Q $$CAPTURA("D ^%WIFI")
 I TN="%CRON" Q $$CAPTURA("D ^%CRON")
 I TN="%AG" Q $$CAPTURA("D ^%AG")
 I TN="%NM" Q $$CAPTURA("D ^%NM")
 I TN="%GL" Q $$CAPTURA("D ^%GL("""_$$ARG(TA,"ns")_""",40)")
 Q "[tool '"_TN_"' sin despacho en %AGENTE]"
 ;
ARG(TA,K) ; lee el campo K de los args JSON (evita romper el M con comillas)
 Q $DEVICE("json:get",TA,K)
 ;
CAPTURA(CMD) ; corre CMD como orden M y devuelve la salida (tras "exit=0")
 N R
 S R=$DEVICE("spawn:run",CMD,15)
 Q $P(R,$C(10),2,99)
 ;
TOOLS() ; (re)escribe el catalogo ^TOOLS base (idempotente). Llama el arranque.
 I '$D(^TOOLS("__names")) S ^TOOLS("__names")="%SS,%GD,%WIFI,%NM,%CRON,%AG,sys:ps,sys:mvm,audio:info,cam:list"
 S ^TOOLS("%SS","desc")="estado del sistema: proceso, RAM, red, DDP, jobs, agentes"
 S ^TOOLS("%SS","kind")="m:%SS"
 S ^TOOLS("%SS","params")="{""type"":""object"",""properties"":{}}"
 S ^TOOLS("%GD","desc")="directorio de globals y rutinas del nodo"
 S ^TOOLS("%GD","kind")="m:%GD"
 S ^TOOLS("%GD","params")="{""type"":""object"",""properties"":{}}"
 S ^TOOLS("%GL","desc")="listado de un global por pantallas (arg: ns)"
 S ^TOOLS("%GL","kind")="m:%GL"
 S ^TOOLS("%GL","params")="{""type"":""object"",""properties"":{""ns"":{""type"":""string""}}}"
 S ^TOOLS("%WIFI","desc")="diagnostico de WiFi: capacidad, config y estado"
 S ^TOOLS("%WIFI","kind")="m:%WIFI"
 S ^TOOLS("%WIFI","params")="{""type"":""object"",""properties"":{}}"
 S ^TOOLS("%NM","desc")="memoria propia del nodo (persistente)"
 S ^TOOLS("%NM","kind")="m:%NM"
 S ^TOOLS("%NM","params")="{""type"":""object"",""properties"":{}}"
 S ^TOOLS("%CRON","desc")="jobs programados del nodo"
 S ^TOOLS("%CRON","kind")="m:%CRON"
 S ^TOOLS("%CRON","params")="{""type"":""object"",""properties"":{}}"
 S ^TOOLS("%AG","desc")="agentes enrutados en el nodo"
 S ^TOOLS("%AG","kind")="m:%AG"
 S ^TOOLS("%AG","params")="{""type"":""object"",""properties"":{}}"
 S ^TOOLS("sys:ps","desc")="procesos del sistema operativo (top por memoria)"
 S ^TOOLS("sys:ps","kind")="d:sys:ps"
 S ^TOOLS("sys:ps","params")="{""type"":""object"",""properties"":{}}"
 S ^TOOLS("sys:mvm","desc")="procesos M del motor (fibers vivos)"
 S ^TOOLS("sys:mvm","kind")="d:sys:mvm"
 S ^TOOLS("sys:mvm","params")="{""type"":""object"",""properties"":{}}"
 S ^TOOLS("audio:info","desc")="tarjetas y dispositivos de audio del nodo"
 S ^TOOLS("audio:info","kind")="d:audio:info"
 S ^TOOLS("audio:info","params")="{""type"":""object"",""properties"":{}}"
 S ^TOOLS("cam:list","desc")="camaras disponibles (locales V4L2 o IP por red)"
 S ^TOOLS("cam:list","kind")="d:cam:list"
 S ^TOOLS("cam:list","params")="{""type"":""object"",""properties"":{}}"
 S ^TOOLS("jobs","desc")="lista de jobs M vivos del nodo (id|estado|seg|rutina)"
 S ^TOOLS("jobs","kind")="d:jobs"
 S ^TOOLS("jobs","params")="{""type"":""object"",""properties"":{}}"
 Q 1
 ;
DEMO ; demo interactiva del bucle
 N P,R
 D TOOLS^%AGENTE()
 W "=== %AGENTE: el LLM que LLAMA tools (DISENO-4 v2) ===",!
 W "Escribe una pregunta (ENTER para salir):",!
 F  D  Q:P=""
 . R P
 . I P="" Q
 . S R=$$CORRE(P)
 . W !,"RESPUESTA: ",R,!
 Q
'''
D = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines/%AGENTE.m")
D.write_text(AG.replace("\n", "\r\n"), encoding="utf-8", newline="")
t = D.read_text(encoding="utf-8")
print(f"escrito: %AGENTE.m ({D.stat().st_size} bytes)")
print("lineas:", t.count("\n"))
print("no-ASCII:", sum(1 for c in t if ord(c) not in (10, 13) and not (32 <= ord(c) < 127)))
print("backslash:", chr(92) in t.replace(chr(92)+'"',"").replace(chr(92)+'n',"").replace(chr(92)+'t',""))
