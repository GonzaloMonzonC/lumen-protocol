"""Ejecutar STUXLATE línea a línea con M-Light."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdb_tools import tool_set, tool_get, tool_m_eval

# SEED: datos que STUXLATE necesita
tool_set({'ns':'SYS','subs':['DEVXLATE','NAME','TEST'],'value':'ASCII_IN^ASCII_OUT'})
tool_set({'ns':'SYS','subs':['DEVXLATE','TABLE','ASCII_IN'],'value':'1^DEC'})
tool_set({'ns':'SYS','subs':['DEVXLATE','TABLE','ASCII_OUT'],'value':'1^DEC'})
print('🔧 Datos seed en ^SYS\n')

# Test 1: $PIECE (línea 6 de STUXLATE)
print('=== Test 1: $PIECE ===')
code = 'S XIN=^SYS("DEVXLATE","NAME","TEST"),XOUT=$P(XIN,"^",2),XIN=$P(XIN,"^",1)'
r = tool_m_eval({'expression': code})
x = tool_m_eval({'expression': 'XIN'})
y = tool_m_eval({'expression': 'XOUT'})
print(f'  XIN={x.get("result")}, XOUT={y.get("result")}')
print(f'  Esperado: XIN=ASCII_IN, XOUT=ASCII_OUT')
ok1 = x.get("result") == "ASCII_IN" and y.get("result") == "ASCII_OUT"

# Test 2: $DATA (línea 5)
print('\n=== Test 2: $DATA ===')
code = '$D(^SYS("DEVXLATE","NAME","TEST"))'
r = tool_m_eval({'expression': code})
print(f'  $DATA = {r.get("result")}')
print(f'  Esperado: 1 (existe valor)')
ok2 = r.get("result") == 1

# Test 3: Comentario (línea 1)
print('\n=== Test 3: Comentario ===')
code = 'STUXLATE(NAME) ;CDS;DEVICE TRANSLATION'
r = tool_m_eval({'expression': code})
print(f'  result = {r.get("result")}')

# Test 4: Acceso directo ^GLOBAL (línea 6 simplificada)
print('\n=== Test 4: ^GLOBAL directo ===')
code = '^SYS("DEVXLATE","NAME","TEST")'
r = tool_m_eval({'expression': code})
print(f'  result = {r.get("result")}')
print(f'  Esperado: ASCII_IN^ASCII_OUT')

# Test 5: NEW (línea 3)
print('\n=== Test 5: NEW ===')
code = 'NEW XADD S XADD=42'
r = tool_m_eval({'expression': code})
print(f'  NEW XADD = {r.get("success")}')

print(f'\n{"="*40}')
print(f'Resultados: {"✅" if ok1 else "❌"} $PIECE, {"✅" if ok2 else "❌"} $DATA')
