#!/usr/bin/env python3
"""Suite de regresión del ecosistema (no romper).
Determinista: health + exec + rutinas clave del MVM. Exit 0 = todo OK.
Los LLM externos (deepseek/Tom) NO se prueban aquí (no deterministas).
"""
import json, subprocess, sys, urllib.request

FAILS = []

def _http(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        body = json.loads(r.read())
    return body

def _exec(code, gas=30000, timeout=40):
    payload = json.dumps({'code': code, 'gas_limit': gas}).encode()
    inner = ('import json,urllib.request;'
             'req=urllib.request.Request("http://127.0.0.1:8082/v1/exec",'
             'data=%r,headers={"Content-Type":"application/json"},method="POST");'
             'print(urllib.request.urlopen(req,timeout=%d).read().decode())' % (payload, timeout - 5))
    p = subprocess.run([sys.executable, '-c', inner], capture_output=True, text=True, timeout=timeout)
    d = json.loads((p.stdout or '').strip() or '{}')
    if not d.get('ok'):
        raise RuntimeError(d.get('error') or 'exec no ok')
    return (d.get('output') or '').strip()

def check(name, fn):
    try:
        fn()
        print(f'[PASS] {name}')
        return True
    except Exception as e:
        print(f'[FAIL] {name}: {e}')
        FAILS.append(name)
        return False

ok = True
ok &= check('vm-api :8081 health', lambda: _http('http://127.0.0.1:8081/health'))
ok &= check('poli :8082 health', lambda: _http('http://127.0.0.1:8082/health'))
ok &= check('exec trivial', lambda: _exec('W "ping"') == 'ping')
ok &= check('rutina FIXER sembrada', lambda: _exec('W $D(^ROUTINE("FIXER"))') == '1')
ok &= check('rutina LLMFREE sembrada', lambda: _exec('W $D(^ROUTINE("LLMFREE"))') == '1')
ok &= check('rutina LLMROUTER sembrada', lambda: _exec('W $D(^ROUTINE("LLMROUTER"))') == '1')
ok &= check('KANBANCNT responde', lambda: _exec('W $$CNT^KANBANCNT()') != '')
ok &= check('FIXLOG escribible', lambda: _exec('S ^FIXLOG($H,"suite")="1" W $G(^FIXLOG($H,"suite"))') == '1')

print(f'\nRESULTADO: {"SUITE VERDE" if not FAILS else f"SUITE ROJA: {FAILS}"}')
sys.exit(0 if not FAILS else 1)
