#!/usr/bin/env python3
"""Test suite completo para Poli MCP Server."""
import json, subprocess, sys, time

srv = subprocess.Popen(
    [sys.executable, 'poli_server.py'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    text=True
)

passed = 0
failed = 0

def rpc(name, args=None, mid=1):
    msg = {'jsonrpc': '2.0', 'id': mid, 'method': name}
    if args: msg['params'] = args
    srv.stdin.write(json.dumps(msg) + '\n')
    srv.stdin.flush()
    return json.loads(srv.stdout.readline())

def test(name, fn):
    global passed, failed
    t = time.time()
    try:
        result = fn()
        elapsed = time.time() - t
        if result is True or result is None or (isinstance(result, dict) and result.get('ok')):
            passed += 1
            print(f"  ✅ {name} ({elapsed:.1f}s)")
        else:
            failed += 1
            print(f"  ❌ {name} ({elapsed:.1f}s): {result}")
    except Exception as e:
        failed += 1
        print(f"  ❌ {name}: {e}")
    return result

rpc('initialize')

# ── 1. SEED ──
print("\n═══ 1. SEED ═══")
def seed():
    r = rpc('tools/call', {'name': 'poli_seed', 'arguments': {}})
    d = json.loads(r['result']['content'][0]['text'])
    return d.get('ok', False)
test('poli_seed', seed)

# ── 2. STATUS ──
print("\n═══ 2. STATUS ═══")
def status():
    r = rpc('tools/call', {'name': 'poli_status', 'arguments': {}})
    d = json.loads(r['result']['content'][0]['text'])
    assert d.get('active_mode') == 'oracle', f"expected oracle, got {d.get('active_mode')}"
    assert d.get('mode_count', 0) >= 3, f"expected >=3 modes, got {d.get('mode_count')}"
    assert 'PERSONALITY' in d.get('routines_loaded', [])
test('poli_status', status)

# ── 3. SWITCH MODES ──
print("\n═══ 3. SWITCH MODES ═══")
for mode in ['mentor', 'critic', 'creative']:
    def make_test(m=mode):
        r = rpc('tools/call', {'name': 'poli_chat', 'arguments': {'mensaje': f'switch {m}', 'mode': m}})
        d = json.loads(r['result']['content'][0]['text'])
        return d.get('ok', False)
    test(f'switch to {mode}', make_test)

# ── 4. LLM ──
print("\n═══ 4. LLM ═══")
def llm_simple():
    r = rpc('tools/call', {'name': 'poli_llm', 'arguments': {'prompt': 'responde solo SI'}})
    d = json.loads(r['result']['content'][0]['text'])
    result = d.get('response', '')
    assert result, "empty response"
    return d.get('ok', False) and len(result) > 0
test('llm simple', llm_simple)

def llm_symbolic():
    r = rpc('tools/call', {'name': 'poli_llm', 'arguments': {'prompt': 'test', 'mode': 'symbolic'}})
    d = json.loads(r['result']['content'][0]['text'])
    return d.get('response') == '[Modo simbólico — sin LLM]'
test('llm symbolic', llm_symbolic)

def llm_with_system():
    r = rpc('tools/call', {'name': 'poli_llm', 'arguments': {
        'prompt': 'cómo estás',
        'system': 'Eres un asistente de una palabra. Responde solo: Bien'
    }})
    d = json.loads(r['result']['content'][0]['text'])
    return d.get('ok', False)
test('llm with system prompt', llm_with_system)

def llm_openrouter():
    r = rpc('tools/call', {'name': 'poli_llm', 'arguments': {
        'prompt': 'responde solo OK',
        'provider': 'openrouter',
        'model': 'deepseek/deepseek-chat'
    }})
    d = json.loads(r['result']['content'][0]['text'])
    result = d.get('response', '')
    return d.get('ok', False) and len(result) > 0
test('llm openrouter provider', llm_openrouter)

# ── 5. FIBER ──
print("\n═══ 5. FIBER ═══")
bg_id = [None]
def bg_spawn():
    r = rpc('tools/call', {'name': 'poli_fiber', 'arguments': {
        'action': 'spawn',
        'source': 'S x=99*99 S ^R=x'
    }})
    d = json.loads(r['result']['content'][0]['text'])
    bg_id[0] = d.get('fiber_id')
    return d.get('action') == 'spawned' and bg_id[0] is not None
test('bg spawn math', bg_spawn)

def bg_join():
    fid = bg_id[0]
    r = rpc('tools/call', {'name': 'poli_fiber', 'arguments': {
        'action': 'join',
        'fiber_id': fid
    }})
    d = json.loads(r['result']['content'][0]['text'])
    return d.get('action') == 'joined' and d.get('result') == '9801'
test('bg join result=9801', bg_join)

def bg_spawn_llm():
    r = rpc('tools/call', {'name': 'poli_fiber', 'arguments': {
        'action': 'spawn',
        'source': 'S r=$DEVICE("llm:call","responde solo GAMMA") S ^R=r'
    }})
    d = json.loads(r['result']['content'][0]['text'])
    return d.get('action') == 'spawned' and d.get('fiber_id') is not None
test('bg spawn LLM', bg_spawn_llm)

# ── 6. HTTP ──
print("\n═══ 6. HTTP ═══")
def http_get():
    r = rpc('tools/call', {'name': 'poli_http', 'arguments': {
        'method': 'get',
        'url': 'https://httpbin.org/get'
    }})
    d = json.loads(r['result']['content'][0]['text'])
    return d.get('ok', False)
test('http GET', http_get)

def http_post():
    r = rpc('tools/call', {'name': 'poli_http', 'arguments': {
        'method': 'post',
        'url': 'https://httpbin.org/post',
        'body': '{"test":42}'
    }})
    d = json.loads(r['result']['content'][0]['text'])
    return d.get('ok', False) and 'httpbin' in (d.get('response') or '')
test('http POST json', http_post)

# ── 7. CHAT FEATURES ──
print("\n═══ 7. CHAT FEATURES ═══")
def chat_personality():
    r = rpc('tools/call', {'name': 'poli_chat', 'arguments': {'mensaje': 'quién eres'}})
    d = json.loads(r['result']['content'][0]['text'])
    return d.get('ok', False)
test('chat quién eres', chat_personality)

def chat_think():
    r = rpc('tools/call', {'name': 'poli_chat', 'arguments': {'mensaje': 'piensa sobre IA'}})
    d = json.loads(r['result']['content'][0]['text'])
    return d.get('ok', False)
test('chat pensar', chat_think)

def chat_memory():
    r = rpc('tools/call', {'name': 'poli_chat', 'arguments': {'mensaje': 'recuerda que mi color favorito es azul'}})
    d = json.loads(r['result']['content'][0]['text'])
    return d.get('ok', False)
test('chat memory save', chat_memory)

def chat_decision():
    r = rpc('tools/call', {'name': 'poli_chat', 'arguments': {'mensaje': 'decide si usar async o sync'}})
    d = json.loads(r['result']['content'][0]['text'])
    return d.get('ok', False) and d.get('decision_id') is not None
test('chat decision log', chat_decision)

# ── 8. EXEC ──
print("\n═══ 8. EXEC ═══")
def exec_math():
    r = rpc('tools/call', {'name': 'poli_exec', 'arguments': {'source': 'S x=2+2 S ^X=x'}})
    d = json.loads(r['result']['content'][0]['text'])
    matches = [g for g in d.get('globals', []) if g.get('name') == '^X' and g.get('value') == 4.0]
    return len(matches) == 1
test('exec math 2+2=4', exec_math)

def exec_loop():
    code = 'S sum=0 F i=1:1:100 S sum=sum+i S ^SUM=sum'
    r = rpc('tools/call', {'name': 'poli_exec', 'arguments': {'source': code}})
    d = json.loads(r['result']['content'][0]['text'])
    matches = [g for g in d.get('globals', []) if g.get('name') == '^SUM' and g.get('value') == 5050.0]
    return len(matches) == 1
test('exec loop 1..100=5050', exec_loop)

def exec_http():
    code = 'S r=$DEVICE("http:get","https://httpbin.org/get") S ^R=r'
    r = rpc('tools/call', {'name': 'poli_exec', 'arguments': {'source': code}})
    d = json.loads(r['result']['content'][0]['text'])
    matches = [g for g in d.get('globals', []) if g.get('name') == '^R']
    return len(matches) > 0 and 'httpbin' in (matches[0].get('value') or '')
test('exec $DEVICE http', exec_http)

def exec_llm():
    code = 'S r=$DEVICE("llm:call","responde solo OK") S ^R=r'
    r = rpc('tools/call', {'name': 'poli_exec', 'arguments': {'source': code, 'gas_limit': 500000}})
    d = json.loads(r['result']['content'][0]['text'])
    return d.get('ok', False)
test('exec $DEVICE llm', exec_llm)

# ── 9. SUMMARY ──
print(f"\n═══ RESULTADOS ═══")
print(f"  ✅ {passed} passed | ❌ {failed} failed | {passed+failed} total")

srv.terminate()
srv.wait()
sys.exit(0 if failed == 0 else 1)
