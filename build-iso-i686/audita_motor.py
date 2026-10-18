#!/usr/bin/env python3
"""AUDITORIA DEL MOTOR M-Light: preguntarle al nodo que sabe hacer.
Bateria de pruebas contra la consola M (puerto 23). Cada linea dice QUE y OK/FALLA.
"""
import socket
import time

IP = "192.168.1.23"
PUERTO = 23


def limpia(b):
    o, i = bytearray(), 0
    while i < len(b):
        if b[i] == 0xFF and i + 2 < len(b):
            i += 3
        else:
            o.append(b[i])
            i += 1
    return bytes(o).decode("utf-8", "replace").replace("\r", "")


def m(cmd, seg=5):
    """Manda un comando y devuelve la salida util."""
    s = socket.create_connection((IP, PUERTO), timeout=40)
    s.settimeout(40)
    time.sleep(0.5)
    s.recv(65536)
    s.sendall((cmd + "\r\n").encode())
    out, fin = b"", time.time() + seg
    while time.time() < fin:
        try:
            d = s.recv(16384)
            if not d:
                break
            out += d
        except socket.timeout:
            break
    s.close()
    r = limpia(out)
    return [
        x.strip()
        for x in r.split("\n")
        if x.strip()
        and "/m" not in x
        and "nodo]" not in x
        and "»" not in x
        and "^CONFIG" not in x
    ]


PRUEBAS = [
    # (etiqueta, comando M)
    ("--- OPERADORES ---", None),
    ("suma 2+3", "/m W 2+3,!"),
    ("division 7/2", "/m W 7/2,!"),
    ("DIVISION ENTERA 7\\2", "/m W 7\\2,!"),
    ("modulo 7#2", "/m W 7#2,!"),
    ("potencia 2**3", "/m W 2**3,!"),
    ("concatenacion 1_2", '/m W 1_2,!'),
    ("--- VARIABLES ESPECIALES ---", None),
    ("$H horolog", "/m W $H,!"),
    ("$J justificar", '/m W "[",$J("x",5),"]",!'),
    ("$P extracto", '/m W $P("a:b:c",":",2),!'),
    ("$E extracto char", '/m W $E("hola",2),!'),
    ("$L longitud", '/m W $L("hola"),!'),
    ("$O order", '/m S k="a" W $O(^SYS(k)),!'),
    ("$D definido", "/m W $D(^SYS),!"),
    ("$G get", '/m W $G(^NOEXISTE,"def"),!'),
    ("$I dispositivo", "/m W $I,!"),
    ("$IO dispositivo", "/m W $IO,!"),
    ("$T test", "/m W $T,!") ,
    ("$S select", '/m W $S(1=1:"si",1:"no"),!'),
    ("$F find", '/m W $F("hola","l"),!'),
    ("$ZJOB", "/m W $ZJOB,!"),
    ("$ZU", "/m W $ZU(0),!"),
    ("--- COMANDOS ---", None),
    ("S/W basico", '/m S X=5 W "X vale ",X,!'),
    ("N new", "/m N X S X=7 W X,!"),
    ("I if", '/m I 1=1 W "if ok",!'),
    ("E else", '/m I 1=2 W "no",! E W "else ok",!'),
    ("F for", '/m F I=1:1:3 W I," ",!'),
    ("F con $O", '/m S k="" F  S k=$O(^SYS(k)) Q:k=""  W k," ",!'),
    ("Q quit en bucle", '/m F I=1:1:9 Q:I=3  W I," ",!'),
    ("POSTCONDICIONAL", '/m W 1,"a",! W 0,"b",! W 1,"c",!'),
    ("X execute", '/m S C="W ""exec ok"",!" X C'),
    ("--- INDIRECCION Y ETIQUETAS ---", None),
    ("indireccion @", '/m S N="X",X=9 W @N,!'),
    ("indireccion global @", '/m S N="^SYS" W $O(@N("")),!'),
    ("$$LABEL^RTN", '/m W $$HOY^%D,!'),
    ("--- RUTINAS NUESTRAS ---", None),
    ("%SS", "/m D ^%SS"),
    ("%HELP zonas", "/m D ZONA^%HELP(\"CONFIGURACION\")"),
    ("%PAGE", "/m D INI^%PAGE W \"pag ok\",!"),
    ("%UTL", '/m D BANNER^%UTL("PRUEBA")'),
    ("%GL paginado", '/m D ^%GL("SYS",5)'),
    ("$DEVICE sys:ps", '/m W $E($DEVICE("sys:ps"),1,90),!'),
    ("$DEVICE sys:top", '/m W $E($DEVICE("sys:top"),1,90),!'),
]

print("=== AUDITORIA DEL MOTOR M-Light ===")
for etq, cmd in PRUEBAS:
    if cmd is None:
        print(f"\n{etq}")
        continue
    r = m(cmd, 5)
    salida = " | ".join(r[:2])[:95] if r else "(vacio)"
    print(f"  {etq:<26} -> {salida}")
