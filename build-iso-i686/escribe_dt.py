#!/usr/bin/env python3
"""%D (fecha) y %T (hora) - ayudantes del MSM, SIN depender de $ZDATE.
El horolog de M: $H = dias desde 1840-12-31 + segundos del dia.
Se convierte con el algoritmo civil-from-days (determinista, solo aritmetica entera)."""
from pathlib import Path

D = r'''%D ; %D · FECHA de hoy (ayudante del MSM) · W $$HOY^%D
 ; En el MSM %D da la fecha y %GD la usa en su banner. Aqui lo mismo.
 ; NO usa $ZDATE (puede no existir en M-Light): se calcula con aritmetica entera
 ; desde el horolog. Determinista y sin dependencias.
HOY() ; fecha de hoy en formato YYYY-MM-DD
 N D
 S D=$P($H,",",1)
 Q $$FMT^%D(D)
FMT(H) ; convierte un dia de horolog a YYYY-MM-DD (algoritmo civil-from-days)
 ; dia 0 del horolog = 1840-12-31 ; el 1-ene-1970 es el dia 47117
 N Z,ERA,DOE,YOE,Y,DOY,MP,M,DD,YY
 S Z=H-47117+719468
 S ERA=Z\146097
 S DOE=Z-(ERA*146097)
 S YOE=(DOE-(DOE\1460)+(DOE\36524)-(DOE\146096))\365
 S Y=YOE+(ERA*400)
 S DOY=DOE-((365*YOE)+(YOE\4)-(YOE\100))
 S MP=(5*DOY+2)\153
 S DD=DOY-((153*MP+2)\5)+1
 S M=MP+3
 I MP>9 S M=MP-9
 S YY=Y
 I M<3 S YY=Y+1
 Q $$C2^%D(YY)_"-"_$$C2^%D(M)_"-"_$$C2^%D(DD)
C2(N) ; dos cifras con cero delante
 I N<10 Q "0"_N
 Q N
'''

T = r'''%T ; %T · HORA actual (ayudante del MSM) · W $$AHORA^%T
 ; El MSM usa %T en el banner (como %D). Aqui: HH:MM:SS desde el horolog.
AHORA() ; hora en formato HH:MM:SS
 N S
 S S=$P($H,",",2)
 Q $$FMT^%T(S)
FMT(S) ; segundos del dia -> HH:MM:SS
 N H,M,R
 S H=S\3600
 S R=S-(H*3600)
 S M=R\60
 S R=R-(M*60)
 Q $$C2^%T(H)_":"_$$C2^%T(M)_":"_$$C2^%T(R)
C2(N) ; dos cifras
 I N<10 Q "0"_N
 Q N
'''

P = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines")
(P / "%D.m").write_text(D.replace("\n", "\r\n"), encoding="utf-8", newline="")
(P / "%T.m").write_text(T.replace("\n", "\r\n"), encoding="utf-8", newline="")
for f in ("%D.m", "%T.m"):
    t = (P / f).read_text(encoding="utf-8")
    print(f"{f}: {len(t)} bytes · {t.count(chr(10))} lineas · indirecciones @(: {t.count('@(')}")

# y engancharlo al %UTL: el banner con fecha y hora (como el MSM)
u = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines/%UTL.m")
s = u.read_text(encoding="utf-8")
if "HOY^%D" not in s:
    s = s.replace(' I N\'="" W "nodo: ",N,!',
                  ' I N\'="" W "nodo: ",N,!\n'
                  ' ; fecha y hora por los ayudantes %D y %T (como hace %GD en el MSM)\n'
                  ' W "fecha: ",$$HOY^%D,"   hora: ",$$AHORA^%T,!')
    u.write_text(s, encoding="utf-8", newline="")
    print("\\n%UTL: banner ahora con FECHA y HORA (via %D y %T)")
