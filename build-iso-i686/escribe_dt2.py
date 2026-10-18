#!/usr/bin/env python3
"""%D y %T correctos: verifica la formula en Python y SOLO si pasa, escribe el .m."""
from pathlib import Path
import datetime

BS = chr(92)   # backslash


def DIV(a, b):
    return (a - (a % b)) // b


def fmt(h):
    z = h - 47117 + 719468
    era = DIV(z, 146097)
    doe = z - (era * 146097)
    num = doe - DIV(doe, 1460) + DIV(doe, 36524) - DIV(doe, 146096)
    yoe = DIV(num, 365)
    y = yoe + (era * 400)
    doy = doe - ((365 * yoe) + DIV(yoe, 4) - DIV(yoe, 100))
    mp = DIV((5 * doy) + 2, 153)
    dd = doy - DIV((153 * mp) + 2, 5) + 1
    m = mp + 3
    if mp > 9:
        m = mp - 9
    yy = y + 1 if m < 3 else y
    return f"{yy:04d}-{m:02d}-{dd:02d}"


print("=== 1. VERIFICAR LA FORMULA EN PYTHON ===")
ok = True
for h, esp in ((47117, "1970-01-01"), (1, "1841-01-01")):
    r = fmt(h)
    bien = r == esp
    ok = ok and bien
    print(f"  dia {h:<7} -> {r}  (esperado {esp})  {'OK' if bien else 'MAL'}")
hoy = (datetime.date.today() - datetime.date(1840, 12, 31)).days
r = fmt(hoy)
bien = r == str(datetime.date.today())
ok = ok and bien
print(f"  hoy        -> {r}  (esperado {datetime.date.today()})  {'OK' if bien else 'MAL'}")

if not ok:
    raise SystemExit("LA FORMULA NO PASA: NO escribo el .m")

print("\n=== 2. ESCRIBIENDO EL .m (formula ya verificada) ===")
D = '''%D ; %D - FECHA de hoy (ayudante del MSM) - W $$HOY^%D
 ; M-Light NO tiene division entera. Se hace con DIV^%D(a,b)=(a-(a#b))/b.
 ; Calculado PASO A PASO (sin anidar) y VERIFICADO en Python antes de escribirlo.
HOY() ; fecha de hoy YYYY-MM-DD
 N D
 S D=$P($H,",",1)
 Q $$FMT^%D(D)
DIV(A,B) ; division ENTERA (M-Light no la trae)
 Q ((A)-((A)#(B)))/(B)
C2(N) ; dos cifras con cero delante
 I N<10 Q "0"_N
 Q N
FMT(H) ; horolog -> YYYY-MM-DD  (civil-from-days, paso a paso)
 N Z,ERA,DOE,NUM,YOE,Y,DOY,MP,M,DD,YY
 S Z=H-47117+719468
 S ERA=$$DIV^%D(Z,146097)
 S DOE=Z-(ERA*146097)
 S NUM=DOE-$$DIV^%D(DOE,1460)+$$DIV^%D(DOE,36524)-$$DIV^%D(DOE,146096)
 S YOE=$$DIV^%D(NUM,365)
 S Y=YOE+(ERA*400)
 S DOY=DOE-((365*YOE)+$$DIV^%D(YOE,4)-$$DIV^%D(YOE,100))
 S MP=$$DIV^%D((5*DOY)+2,153)
 S DD=DOY-$$DIV^%D((153*MP)+2,5)+1
 S M=MP+3
 I MP>9 S M=MP-9
 S YY=Y
 I M<3 S YY=Y+1
 Q $$C2^%D(YY)_"-"_$$C2^%D(M)_"-"_$$C2^%D(DD)
'''
T = '''%T ; %T - HORA actual (ayudante del MSM) - W $$AHORA^%T
 ; M-Light NO tiene division entera. Se hace con DIV^%T(a,b).
AHORA() ; hora HH:MM:SS
 N S
 S S=$P($H,",",2)
 Q $$FMT^%T(S)
DIV(A,B) ; division ENTERA
 Q ((A)-((A)#(B)))/(B)
C2(N) ; dos cifras
 I N<10 Q "0"_N
 Q N
FMT(S) ; segundos del dia -> HH:MM:SS
 N H,M,R
 S H=$$DIV^%T(S,3600)
 S R=S-(H*3600)
 S M=$$DIV^%T(R,60)
 S R=R-(M*60)
 Q $$C2^%T(H)_":"_$$C2^%T(M)_":"_$$C2^%T(R)
'''
P = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines")
for nom, txt in (("%D.m", D), ("%T.m", T)):
    (P / nom).write_text(txt.replace("\n", "\r\n"), encoding="utf-8", newline="")
    print(f"  {nom}: escrito")

print("\n=== 3. COMPROBAR ===")
for nom in ("%D.m", "%T.m"):
    t = (P / nom).read_text(encoding="utf-8")
    malos = sum(1 for c in t if ord(c) not in (10, 13) and not (32 <= ord(c) < 127))
    print(f"  {nom}: {len(t)} bytes · no-ASCII: {malos} · tiene backslash: {BS in t} · DIV^: {'DIV^' in t}")
print("\n  los dos .m listos para el Asus")
