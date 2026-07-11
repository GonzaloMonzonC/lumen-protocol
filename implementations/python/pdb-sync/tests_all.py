"""Tests: Network Agent + Workspace + Service Registry + DDP core."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from pdb_docs import _get_pdb_tools; t = _get_pdb_tools()
from pdb_network_agent import *
from pdb_agent_workspace import *
from pdb_service_registry import *
from pdb_ddp import ddp_register_node, ddp_list_nodes, ddp_add_link, ddp_open_circuit, ddp_send

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS PDB NETWORK AGENT')
r = net_cycle()
test("cycle runs", isinstance(r, dict))
test("cycle has checked", r.get('checked'))

dead = net_check_heartbeats()
test("check returns list", isinstance(dead, list))

r = net_reconnect('hermes')
test("reconnect returns agent", r.get('agent') == 'hermes')
test("reconnect has nonce", len(r.get('nonce','')) > 0)

s = net_status()
test("status has total", s.get('total', 0) >= 0)

print('\n🧪 TESTS AGENT WORKSPACE')
ws_set('test-agent', 'k1', 'v1', ttl=60)
test("ws_set stores", ws_get('test-agent', 'k1') == 'v1')
test("ws_list finds", 'k1' in ws_list('test-agent'))

ws_set('test-agent', 'k2', {'a': 1}, ttl=60)
test("ws_set dict", ws_get('test-agent', 'k2').get('a') == 1)

keys = ws_list('test-agent')
test("ws_list count", len(keys) >= 2)

print('\n🧪 TESTS SERVICE REGISTRY')
registry_init()
s = registry_lookup('query')
test("registry lookup", s is not None)
test("registry has agent", s.get('agent') == 'zalo')

tom_svcs = registry_by_agent('tom')
test("tom has services", len(tom_svcs) >= 3)

all_svcs = registry_list()
test("registry total", len(all_svcs) >= 10)

print('\n🧪 TESTS DDP CORE')
ddp_register_node('test1', 'local')
ddp_register_node('test2', 'remote')
nodes = ddp_list_nodes()
test("ddp nodes registered", len(nodes) >= 2)

ddp_add_link('t1→t2', 'test2')
c = ddp_open_circuit('test1', 'test2')
test("circuit opened", c is not None)

r = ddp_send(c['id'], 'ping', {'msg': 'hello'})
test("message sent", r.get('success'))

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
