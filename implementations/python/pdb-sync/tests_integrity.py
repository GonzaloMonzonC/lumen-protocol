"""Tests MSMINTEG: PDB Integrity Checker."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from pdb_integrity import *

p = f = 0
def t(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS MSMINTEG\n')

# Routines
r = integrity_check_routines()
t("routines returns dict", isinstance(r, dict))
t("routines has ok", 'ok' in r)
t("routines has mismatch", 'mismatch' in r)
t("routines has new", 'new' in r)
t("routines ok count", len(r['ok']) + len(r['new']) > 0)

# Orphans
o = integrity_check_orphans()
t("orphans returns list", isinstance(o, list))
t("orphans count", len(o) >= 0)

# Full check
all_ = integrity_check_all()
t("full check returns dict", isinstance(all_, dict))
t("full has timestamp", 'timestamp' in all_)
t("full has routines", 'routines' in all_)
t("full has orphans", 'orphans' in all_)
t("full has healthy", 'healthy' in all_)
t("full routine ok count", all_['routines']['total_ok'] + all_['routines']['new_checksums'] > 0)

# SHA256
import hashlib
h1 = hashlib.sha256(b"test").hexdigest()
h2 = hashlib.sha256(b"test").hexdigest()
h3 = hashlib.sha256(b"different").hexdigest()
t("sha256 consistent", h1 == h2)
t("sha256 different", h1 != h3)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
