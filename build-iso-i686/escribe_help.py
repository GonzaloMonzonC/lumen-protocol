#!/usr/bin/env python3
"""^HELP por zonas (como el MSM): el help VIVE EN DATOS, no en codigo.
  ^HELP(0,"<ZONA>")   = las zonas
  ^HELP("<CLAVE>",0)  = el titular
  ^HELP("<CLAVE>",N)  = la linea N
Mas el LECTOR %HELP: zonas -> claves -> leer -> paginar. Sin indireccion @."""
from pathlib import Path

HELP = r'''%HELP ; %HELP · AYUDA POR ZONAS (estilo MSM: el help vive en DATOS)
 ; Uso:  D ^%HELP            -> explorar por zonas
 ;       D ZONA^%HELP("CONFIGURACION")  -> claves de una zona
 ;       D VER^%HELP("WIFI")           -> leer una entrada
 ;       D SEMILLA^%HELP               -> (re)escribir la ayuda base
 ;
 ; POR QUE ASI: en el MSM el help NO va en codigo, vive en el global:
 ;     ^HELP(0,"<ZONA>")   las zonas
 ;     ^HELP("<CLAVE>",0)  el titular
 ;     ^HELP("<CLAVE>",N)  la linea N
 ; -> se puede AMPLIAR sin recompilar nada.
 ;
 N Z
 D SEMILLA^%HELP
 D INI^%PAGE
 D BANNER^%UTL("AYUDA - ZONAS")
 S Z=""
 F  S Z=$O(^HELP(0,Z)) Q:Z=""  D
 . S %C=$O(^HELP(Z,""),1)
 . W "  ",Z,!
 W !
 W "Para ver una zona:  D ZONA^%HELP(\"<ZONA>\")",!
 W "Para leer una clave: D VER^%HELP(\"<CLAVE>\")",!
 D MAS^%PAGE
 D FIN^%PAGE
 Q
 ;
ZONA(Z) ; lista las claves de una zona
 N K,N
 D INI^%PAGE
 D BANNER^%UTL("ZONA: "_Z)
 S N=0,K=""
 F  S K=$O(^HELP(Z,K)) Q:K=""  S N=N+1 W "  ",K,!
 D MAS^%PAGE
 D FIN^%PAGE
 W "(",N," entradas)",!
 Q
 ;
VER(K) ; lee una entrada: titular + lineas, paginando
 N I,T
 D INI^%PAGE
 I '$D(^HELP(K)) W "No hay ayuda para '",K,"'. ",! D FIN^%PAGE Q
 S T=$G(^HELP(K,0))
 D BANNER^%UTL(T)
 S I=0
 F  S I=$O(^HELP(K,I)) Q:I=""  D
 . W "  ",$G(^HELP(K,I)),!
 . D MAS^%PAGE
 D FIN^%PAGE
 Q
 ;
SEMILLA ; escribe la ayuda base (idempotente: no pisa lo que ya hay)
 D ZZONAS^%HELP
 D ZCONF^%HELP
 D ZDIAG^%HELP
 D ZDATOS^%HELP
 D ZRUT^%HELP
 D ZRED^%HELP
 D ZSIS^%HELP
 D ZFIC^%HELP
 W:0 ""
 Q
 ;
ZZONAS ; las 7 zonas
 I '$D(^HELP(0,"CONFIGURACION")) S ^HELP(0,"CONFIGURACION")="wifi, hub DDP, identidad, llm"
 I '$D(^HELP(0,"DIAGNOSTICO")) S ^HELP(0,"DIAGNOSTICO")="%WIFI, %SS, drivers, red"
 I '$D(^HELP(0,"DATOS")) S ^HELP(0,"DATOS")="PDB, memoria por nodo, tablon"
 I '$D(^HELP(0,"RUTINAS")) S ^HELP(0,"RUTINAS")="editor, guardar, listar"
 I '$D(^HELP(0,"RED Y DDP")) S ^HELP(0,"RED Y DDP")="nodos vivos, enviar, HMAC+ID"
 I '$D(^HELP(0,"SISTEMA")) S ^HELP(0,"SISTEMA")="apagar, reiniciar, estado"
 I '$D(^HELP(0,"FICCION")) S ^HELP(0,"FICCION")="voces prestadas"
 Q
 ;
E(Z,K,T,L1,L2,L3) ; escribe una entrada si no existe
 I $D(^HELP(K)) Q
 S ^HELP(Z,K)=""
 S ^HELP(K,0)=T
 I L1'="" S ^HELP(K,1)=L1
 I L2'="" S ^HELP(K,2)=L2
 I L3'="" S ^HELP(K,3)=L3
 Q
 ;
ZCONF ;
 D E^%HELP("CONFIGURACION","WIFI","WiFi del nodo","Se configura en /etc/wifi.conf (SSID, PSK, OCULTA).","Para forzar la prueba aunque haya cable: FORZAR=si o 'lumenwifi' al arrancar.","Diagnostico: D ^%WIFI")
 D E^%HELP("CONFIGURACION","HUB","Hub DDP (el circulo)","En /etc/hub.conf: HUB=<ip> y DDP_KEY=<clave HMAC>.","El nodo empuja su identidad firmada (X-DDP-Node + X-DDP-HMAC2).","Ver los nodos vivos: D ^%NODOS")
 D E^%HELP("CONFIGURACION","NODO","Nombre del nodo","Prioridad: cmdline nodo= > /etc/nodo.conf > DMI > ^SYS(\"NODO\").","El valor sembrado en la PDB es el ULTIMO recurso (miente si no hay nada mas).","Ver quien soy: D ^%SS")
 D E^%HELP("CONFIGURACION","LLM","Motor de lenguaje","^CONFIG(\"llm_url_openrouter\") apunta al nodo-puerta.","Gratis primero; el de pago solo excepcional.")
 Q
 ;
ZDIAG ;
 D E^%HELP("DIAGNOSTICO","%WIFI","Diagnostico de WiFi","Vuelca capacidad, config y estado del hub.","Usa el shell :2323 para iwconfig, dmesg, rfkill.","")
 D E^%HELP("DIAGNOSTICO","%SS","Estado del sistema (top)","D ^%SS = foto completa. D ^%SS(\"M\") = procesos M.","Cuenta los globals EN VIVO, no el valor sembrado.","")
 D E^%HELP("DIAGNOSTICO","RED","Red del nodo","eth0 (cable) y wlan0 (WiFi). La WiFi asocia y pide IP sola.","Si no hay IP: cat /tmp/uw.log muestra lo que dijo udhcpc.","")
 Q
 ;
ZDATOS ;
 D E^%HELP("DATOS","MEMORIA","Memoria propia del nodo","Cada nodo tiene ^NODO(<id>). Se guarda en el hub y se recupera al arrancar.","Es memoria PERSISTENTE SIN DISCO: la PDB vive en RAM, el hub guarda copia.","")
 D E^%HELP("DATOS","TABLON","Tablon compartido (por hacer)","Un tablon general y uno por tema, donde los nodos avisan y colaboran.","El autor va FIRMADO con la identidad del nodo.","")
 Q
 ;
ZRUT ;
 D E^%HELP("RUTINAS","%GD","Directorio de globals","Lista namespaces y rutinas con sus tamanos.","")
 D E^%HELP("RUTINAS","EDITOR","Editor de rutinas","Guardar: /m :save NOMBRE (^EDIT) y recarga.","")
 Q
 ;
ZRED ;
 D E^%HELP("RED Y DDP","NODOS","Nodos del circulo","GET /ddp/nodes en el hub: nombre, IP, CPU y RAM de cada nodo vivo.","")
 D E^%HELP("RED Y DDP","HMACID","HMAC + ID (por hacer)","Con la clave HMAC y un ID (URL o IP) se podra alcanzar cualquier maquina","accesible, tambien por internet. La firma con identidad ya esta hecha.","")
 Q
 ;
ZSIS ;
 D E^%HELP("SISTEMA","APAGAR","Apagar / reiniciar (por hacer)","Ordenes para apagar o reiniciar el nodo desde la consola.","")
 Q
 ;
ZFIC ;
 D E^%HELP("FICCION","VOCES","Voces prestadas","Cambiar de personalidad con una orden corta, sin teclear comandos cada vez.","")
 Q
'''

D = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines/%HELP.m")
D.write_text(HELP.replace("\n", "\r\n"), encoding="utf-8", newline="")
t = D.read_text(encoding="utf-8")
print(f"escrito: %HELP.m ({D.stat().st_size} bytes, {t.count(chr(10))} lineas)")
print("indirecciones @(:", t.count("@("), "(debe ser 0)")
print("zonas definidas:", t.count('^HELP(0,"'))
print("entradas E^%HELP:", t.count("D E^%HELP("))
