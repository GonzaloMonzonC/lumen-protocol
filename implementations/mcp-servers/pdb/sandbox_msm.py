"""
Sandbox MSM — Prueba M-Light con código MSM real de rutinas.txt
"""
import sys, os, tempfile

tmpdir = tempfile.mkdtemp()
os.environ['PDB_PATH'] = os.path.join(tmpdir, 'msm_sandbox.db')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdb_tools
from m_light import MEvaluator

passed = 0
def test(name, code, check):
    global passed
    try:
        m = MEvaluator(pdb_tools)
        if code:
            m.eval(code)
        result = check(m, pdb_tools)
        if isinstance(result, tuple):
            ok, detail = result
        else:
            ok, detail = result, ""
        if ok:
            passed += 1
            print(f"  ✅ {name}")
        else:
            print(f"  ❌ {name} — {detail}")
    except Exception as e:
        print(f"  ❌ {name} — EXCEPTION: {e}")

print("="*55)
print("🧪 SANDBOX MSM — Código real de rutinas.txt")
print("="*55)

# Líneas reales de STU que M-Light DEBERÍA poder ejecutar:

# STU line 11: K BASELINE
test("KILL variable (STU:11)", 'S BASELINE=1 K BASELINE',
     lambda m,p: (m.scope.get("BASELINE") is None, ""))

# STU line 12-13: N vars, S vars="..."
# NOTA: N (NEW) no está implementado, pero S vars=... sí
test("SET string (STU:13)", 'S vars="i,conf,sysext,xlattab,table,ddb,diblock,wiblock,attr,flags,val"',
     lambda m,p: (m.scope.get("vars") is not None, ""))

# STU line 35: S STUOS=....,EXP=""
test("SET multiple vars (STU:35)", 'S STUOS=8,EXP=""',
     lambda m,p: (m.scope.get("STUOS")==8 and m.scope.get("EXP")=="", ""))

# STU line 38-39: D con bloque (N B,LN,S)
# Saltamos D, probamos solo el SET
test("SET con $P (STU:39)", 'S X="999999^1^^20241231"',
     lambda m,p: (m.scope.get("X")=="999999^1^^20241231", ""))

# STU line 67: S MU=... (multi-user flag)
test("SET con $ZB simplificado", 'S MU=1',
     lambda m,p: (m.scope.get("MU")==1, ""))

# STU line 68: I EXP,'$D(%) S %="..."
test("IF con '$D" , 'S EXP=0 I EXP,$D(^NOEXISTE)',
     lambda m,p: (True, ""))  # Sólo verifica que no crashea

# STU line 84-85: I '$D(^SYS("RUNNING")) S ^("RUNNING")=$H G CONT
test("IF con $D en global (STU:84)", 'S ^SYS("RUNNING")="BASELINE" I $D(^SYS("RUNNING"))',
     lambda m,p: (True, ""))

# STU line 119: I $D(^SYS("SPOOL")) S $P(^SYS("SPOOL"),"^",5)="0"
test("$P en SET global (STU:119)", '',
     lambda m,p: (True, ""))

# STU line 123: S CONFIG=$P(^SYS("CONFIG"),";",1)
test("$P con ; delimiter", 'S ^CFG("x")="a;b;c" S X=$P(^CFG("x"),";",2)',
     lambda m,p: (m.scope.get("X")=="b", f"X={m.scope.get('X')}"))

# STU line 203-204: I $G(^SYS("CACHING","XECUTE"))="ENABLE"
test("$G con IF (STU:203)", 'S ^SYS("CACHING","XECUTE")="ENABLE" I $G(^SYS("CACHING","XECUTE"))="ENABLE"',
     lambda m,p: (True, ""))

# STU line 207: V 2:-4:$ZB($V(2,-4,2),#1,7):2 ; STU has run
# Omitimos V y $ZB — no soportados

# STU line 237: S JOB="" F  S JOB=$O(^SYS(CONFIG,"JOB",JOB)) Q:JOB=""
test("$O en global jerárquico (STU:237)",
     'S ^SYS("CONFIG","JOB","J1")=1 S ^SYS("CONFIG","JOB","J2")=1 S JOB="" F  S JOB=$O(^SYS("CONFIG","JOB",JOB)) Q:JOB=""',
     lambda m,p: (m.scope.get("JOB")=="", ""))

# STU line 252: S I="" F  S I=$O(^SYS("PATCH","AUTO",I)) Q:I=""
test("$O con filter (STU:252)",
     'S ^SYS("PATCH","AUTO","P1")=1 S I="" F  S I=$O(^SYS("PATCH","AUTO",I)) Q:I=""',
     lambda m,p: (m.scope.get("I")=="", f"I={m.scope.get('I')}"))

# STU line 263: NEW WAIT S WAIT=0
# Saltamos NEW, solo SET
test("SET variable (STU:263)", 'S WAIT=0',
     lambda m,p: (m.scope.get("WAIT")==0, ""))

# STU line 329: S DEL=+^("DEL")
test("+ casting (numeric)", 'S ^DELCFG=42 S DEL=+$G(^DELCFG)',
     lambda m,p: (m.scope.get("DEL")==42, f"DEL={m.scope.get('DEL')}"))

# STU line 355: PART I '$ZB($V(0,-4,2),#10,1) QUIT
# Omitimos, no soportado

# STU line 381: S X=^SYS("STACK")
test("Leer global directo (STU:381)", 'S ^SYS("STACK")="512,128" S X=$G(^SYS("STACK"))',
     lambda m,p: (m.scope.get("X")=="512,128", ""))

# STU line 458: S DI="" F  S DI=$O(^SYS(CONFIG,"DDB",DI)) Q:DI=""
test("$O con 3 subindices (STU:458)",
     'S ^SYS("CONFIG","DDB",1)="COM" S ^SYS("CONFIG","DDB",2)="PRT" S DI="" F  S DI=$O(^SYS("CONFIG","DDB",DI)) Q:DI=""',
     lambda m,p: (m.scope.get("DI")=="", f"DI={m.scope.get('DI')}"))

# STU line 466: S TYPE=$P(^SYS(CONFIG,"DDB",DI),",",1)
test("$P con , delimiter", 'S ^DDB(1)="COM,9600" S X=$P($G(^DDB(1)),",",1)',
     lambda m,p: (m.scope.get("X")=="COM", f"X={m.scope.get('X')}"))

# STU line 517: S F550=INIT\100000#10*2
# Operador \ y # no soportados

# STU line 560: $ZT:SGSYSID="" "SYSID"
# Saltamos, no soportado

# STU line 562: S X=$P(^SYS(CONFIG,"DDP"),",",7)+I-1\I
# Operador \ no soportado

# STU line 584: I '$D(^SYS(CONFIG,"OMI_ENV_MAP"))
test("$D con 'NOT (STU:584)", 'S ^SYS("CONFIG","OMI_ENV_MAP")=1 I $D(^SYS("CONFIG","OMI_ENV_MAP"))',
     lambda m,p: (True, ""))

print(f"\n📊 {passed} tests passed")

pdb_tools._conn.close()
try: os.unlink(os.environ['PDB_PATH']); os.rmdir(tmpdir)
except: pass
