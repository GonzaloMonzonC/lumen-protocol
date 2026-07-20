#!/usr/bin/env python3
"""Test suite EXTENDIDO para Poli MCP Server — performance + edge cases."""
import json, subprocess, sys, time

srv = subprocess.Popen(
    [sys.executable, 'poli_server.py'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    text=True
)

passed = 0
failed = 0

def rpc(name, args=None):
    msg = {'jsonrpc': '2.0', 'id': 1, 'method': name}
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
        if result is True or result is None:
            passed += 1
            print(f"  ✅ {name} ({elapsed:.1f}s)")
            return result, elapsed
        else:
            failed += 1
            print(f"  ❌ {name} ({elapsed:.1f}s): {result}")
            return result, elapsed
    except Exception as e:
        failed += 1
        print(f"  ❌ {name}: {e}")
        return False, 0

def call(name, args):
    r = rpc('tools/call', {'name': name, 'arguments': args})
    return json.loads(r['result']['content'][0]['text'])

rpc('initialize')
call('poli_seed', {})

# ══════════════════════════════════════════════════════════════
# PERFORMANCE: PARALELISMO FIBER BG vs SECUENCIAL
# ══════════════════════════════════════════════════════════════
print("═══ PERFORMANCE: FIBER BG vs SECUENCIAL ═══")

def perf_bg_parallel():
    """2 bg fibers con LLM ejecutándose en paralelo real."""
    t0 = time.time()
    r1 = call('poli_fiber', {'action': 'spawn', 'source': 'S r=$DEVICE("llm:call","responde solo A") S ^R=r'})
    r2 = call('poli_fiber', {'action': 'spawn', 'source': 'S r=$DEVICE("llm:call","responde solo B") S ^R=r'})
    id_a, id_b = r1.get('fiber_id'), r2.get('fiber_id')
    
    ra, _ = None, None
    for rid in [id_a, id_b]:
        r = call('poli_fiber', {'action': 'join', 'fiber_id': rid})
        if r.get('result'): ra = r.get('result')
    elapsed = time.time() - t0
    return elapsed < 15 and ra is not None  # 2 LLM en <15s

t, elapsed = test("2 bg fibers paralelo (LLM)", perf_bg_parallel)
print(f"   → tiempo total: {elapsed:.1f}s")

def perf_sequential():
    """2 LLM calls secuenciales como baseline."""
    t0 = time.time()
    r1 = call('poli_llm', {'prompt': 'responde solo X'})
    r2 = call('poli_llm', {'prompt': 'responde solo Y'})
    elapsed = time.time() - t0
    return elapsed < 15

t, seq_elapsed = test("2 LLM secuencial (baseline)", perf_sequential)
print(f"   → tiempo total: {seq_elapsed:.1f}s")

# ══════════════════════════════════════════════════════════════
# HTTP EDGE CASES
# ══════════════════════════════════════════════════════════════
print("\n═══ HTTP EDGE CASES ═══")

def http_404():
    r = call('poli_http', {'method': 'get', 'url': 'https://httpbin.org/status/404'})
    return r.get('ok', False)
test("HTTP 404", http_404)

def http_302():
    r = call('poli_http', {'method': 'get', 'url': 'https://httpbin.org/redirect/1'})
    return r.get('ok', False)
test("HTTP redirect 302", http_302)

def http_long_url():
    r = call('poli_http', {'method': 'get', 'url': 'https://httpbin.org/uuid'})
    return r.get('ok', False) and r.get('response') is not None
test("HTTP /uuid", http_long_url)

def http_empty_body():
    r = call('poli_http', {'method': 'post', 'url': 'https://httpbin.org/post', 'body': ''})
    return r.get('ok', False)
test("HTTP POST body vacío", http_empty_body)

def http_invalid_url():
    r = call('poli_http', {'method': 'get', 'url': 'https://thissitedoesnotexist999999999.com/'})
    return not r.get('ok', True)  # Debe fallar (conexión imposible)
test("HTTP URL inválida → error", http_invalid_url)

# ══════════════════════════════════════════════════════════════
# LLM EDGE CASES
# ══════════════════════════════════════════════════════════════
print("\n═══ LLM EDGE CASES ═══")

def llm_empty_prompt():
    r = call('poli_llm', {'prompt': ''})
    return not r.get('ok', False)  # Debe fallar con prompt vacío
test("LLM prompt vacío → error", llm_empty_prompt)

def llm_long_prompt():
    prompt = "responde solo " + "OK" * 50
    r = call('poli_llm', {'prompt': prompt})
    return r.get('ok', False)
test("LLM prompt largo (100 chars)", llm_long_prompt)

def llm_rapid_fire():
    """3 LLM calls rápidas en secuencia."""
    t0 = time.time()
    for i in range(3):
        r = call('poli_llm', {'prompt': f'responde solo {i}'})
        if not r.get('ok'): return False
    return time.time() - t0 < 20
test("LLM 3 rápidas seguidas", llm_rapid_fire)

# ══════════════════════════════════════════════════════════════
# FIBER EDGE CASES
# ══════════════════════════════════════════════════════════════
print("\n═══ FIBER EDGE CASES ═══")

def fiber_join_invalid():
    r = call('poli_fiber', {'action': 'join', 'fiber_id': 99999})
    return not r.get('ok', True)  # Debe fallar (ID no existe)
test("FIBER join ID inválido → error", fiber_join_invalid)

def fiber_bg_complex():
    """bg fiber con loop y condiciones."""
    code = 'S sum=0 F i=1:1:50 S sum=sum+i S ^R=sum'
    r = call('poli_fiber', {'action': 'spawn', 'source': code})
    fid = r.get('fiber_id')
    r2 = call('poli_fiber', {'action': 'join', 'fiber_id': fid})
    return r2.get('result') == '1275'  # 1..50 = 1275
test("FIBER bg loop 1..50=1275", fiber_bg_complex)

def fiber_bg_nested():
    """bg fiber que llama $DEVICE y $FIBER."""
    code = 'S r=$DEVICE("http:get","https://httpbin.org/uuid") S ^R=r'
    r = call('poli_fiber', {'action': 'spawn', 'source': code})
    fid = r.get('fiber_id')
    r2 = call('poli_fiber', {'action': 'join', 'fiber_id': fid})
    return r2.get('ok', False)
test("FIBER bg + $DEVICE HTTP", fiber_bg_nested)

# ══════════════════════════════════════════════════════════════
# EXEC EDGE CASES
# ══════════════════════════════════════════════════════════════
print("\n═══ EXEC EDGE CASES ═══")

def exec_empty():
    r = call('poli_exec', {'source': ''})
    return not r.get('ok', False)
test("EXEC source vacío → error", exec_empty)

def exec_long_loop():
    code = 'S x=0 F i=1:1:1000 S x=x+i S ^X=x'
    r = call('poli_exec', {'source': code, 'gas_limit': 500000})
    return r.get('ok', False)
test("EXEC loop 1..1000 (gas alto)", exec_long_loop)

def exec_chain():
    """M code que encadena $DEVICE("llm:call") con http."""
    code = """
        S llm=$DEVICE("llm:call","responde solo OK")
        S http=$DEVICE("http:get","https://httpbin.org/uuid")
        S ^LLM=llm S ^HTTP=http
    """
    r = call('poli_exec', {'source': code, 'gas_limit': 500000})
    found_llm = any(g.get('name') == '^LLM' for g in r.get('globals', []))
    found_http = any(g.get('name') == '^HTTP' for g in r.get('globals', []))
    return r.get('ok', False) and found_llm and found_http
test("EXEC $DEVICE(llm) + http combinado", exec_chain)

# ══════════════════════════════════════════════════════════════
# CHAT EDGE CASES
# ══════════════════════════════════════════════════════════════
print("\n═══ CHAT EDGE CASES ═══")

def chat_no_message():
    r = call('poli_chat', {'mensaje': ''})
    return not r.get('ok', False)
test("CHAT mensaje vacío → error", chat_no_message)

def chat_emoji():
    r = call('poli_chat', {'mensaje': 'piensa sobre 🦀 Rust 🚀'})
    return r.get('ok', False)
test("CHAT con emojis", chat_emoji)

def chat_multiple_memories():
    """Guarda y recupera múltiples memorias."""
    topics = ['mi color favorito es verde', 'me gusta el café', 'odio las entregas tardías']
    for t in topics:
        r = call('poli_chat', {'mensaje': f'guarda que {t}'})
        if not r.get('ok'): return False
    r2 = call('poli_chat', {'mensaje': 'recuerda algo'})
    mems = r2.get('memories', [])
    return len(mems) >= 1
test("CHAT múltiples memorias", chat_multiple_memories)

# ══════════════════════════════════════════════════════════════
# STATE INTEGRITY
# ══════════════════════════════════════════════════════════════
print("\n═══ STATE INTEGRITY ═══")

def state_persistent():
    """El estado de Poli persiste entre tools."""
    r1 = call('poli_exec', {'source': 'S ^MYFLAG=42'})
    r2 = call('poli_exec', {'source': 'S ^R=$G(^MYFLAG)'})
    matches = [g.get('value') for g in r2.get('globals', []) if g.get('name') == '^R']
    return len(matches) > 0 and matches[0] == 42
test("Globales persisten entre calls", state_persistent)

def state_active_mode():
    """Modo activo se mantiene tras switch."""
    call('poli_chat', {'mensaje': 'switch critic', 'mode': 'critic'})
    s = call('poli_status', {})
    return s.get('active_mode') == 'critic'
test("Modo activo persistente", state_active_mode)

# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════
print(f"\n═══ RESULTADOS EXTENDIDOS ═══")
print(f"  ✅ {passed} passed | ❌ {failed} failed | {passed+failed} total ({passed+failed-22} nuevos)")

if passed > 0 and (passed+failed) > 0:
    print(f"  📊 Tasa de éxito: {100*passed/(passed+failed):.0f}%")

srv.terminate()
srv.wait()
sys.exit(0 if failed == 0 else 1)
