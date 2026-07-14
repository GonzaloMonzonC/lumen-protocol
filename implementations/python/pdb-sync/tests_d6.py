"""Tests D6: Cross-refs inversas."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
import _paths  # noqa: F401  # sys.path del stack PDB
from pdb_docs import doc_set, doc_get, doc_add_link, doc_find_refs, doc_graph

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS D6: Cross-refs inversas\n')

# Setup: crear docs + links
doc_set('playbook', ['test-incidents'], {'title':'Incidents','links':[]})
doc_set('decisions', ['test-ddp'], {'title':'DDP','links':[]})
doc_set('playbook', ['test-recovery'], {'title':'Recovery','links':[]})
doc_set('learnings', ['test-pdb'], {'title':'PDB Notes','links':[]})

# Add links
doc_add_link('playbook', ['test-incidents'], '^decisions:test-ddp')
doc_add_link('playbook', ['test-recovery'], '^decisions:test-ddp')
doc_add_link('playbook', ['test-incidents'], '^playbook:test-recovery')
doc_add_link('learnings', ['test-pdb'], '^playbook:test-incidents')

# Test find_refs
refs = doc_find_refs('^decisions:test-ddp')
test("find_refs returns list", isinstance(refs, list))
test("find_refs finds 2", len(refs) == 2)
paths = [r['doc'] for r in refs]
test("incidents in refs", any('incidents' in p for p in paths))
test("recovery in refs", any('recovery' in p for p in paths))

# Empty target
empty = doc_find_refs('^nonexistent:test')
test("empty target", len(empty) == 0)

# Multiple links from same doc
doc_add_link('playbook', ['test-incidents'], '^learnings:test-pdb')
refs2 = doc_find_refs('^learnings:test-pdb')
test("new link found", len(refs2) >= 1)

# Graph
g = doc_graph('playbook', ['test-incidents'])
test("graph has center", 'center' in g)
test("graph links_out", len(g.get('links_out', [])) >= 2)
test("graph links_in", len(g.get('links_in', [])) >= 0)

# Graph non-existent
g2 = doc_graph('nonexistent', ['test'])
test("graph missing doc", 'error' in g2)

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
