"""
MUMPS Console Utilities for PDB
================================
D ^%SS  — System Status (namespace sizes, health)
D ^%GL  — Global Listing (show all namespaces and sample data)
D ^%GI  — Global Inspection (browse a specific ^GLOBAL)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdb_tools import HANDLERS

def pct_SS():
    """System Status — muestra todos los namespaces y sus tamaños"""
    print("=== PDB System Status (^%SS) ===")
    schema = HANDLERS['pdb_schema']({})
    if not schema.get('success'):
        print("ERROR: no se pudo leer el schema")
        return
    
    print(f"DB: {schema['database']}")
    print(f"Size: {schema['size_bytes']/1024/1024:.0f} MB")
    print()
    print(f"{'Namespace':20s} {'Nodes':>6s} {'Values':>6s} {'Empty':>6s}")
    print("-" * 42)
    
    for ns in schema['namespaces']:
        print(f"{ns['ns']:20s} {ns['nodes']:6d} {ns['with_values']:6d} {ns['structural']:6d}")
    
    total = sum(n['nodes'] for n in schema['namespaces'])
    print("-" * 42)
    print(f"{'TOTAL':20s} {total:6d}")

def pct_GL(ns=None):
    """Global Listing — muestra estructura de un ^GLOBAL"""
    if ns is None:
        schema = HANDLERS['pdb_schema']({})
        namespaces = [n['ns'] for n in schema.get('namespaces', [])]
        print("=== Global Listing (^%GL) ===")
        print(f"Namespaces: {', '.join(namespaces)}")
        print("Usa ^%GI(namespace) para inspeccionar uno.")
        return
    
    print(f"=== ^%GI — {ns} ===")
    I = ''
    count = 0
    while count < 10:
        r = HANDLERS['pdb_order']({'ns': ns, 'subs': [I]})
        if not r.get('value'):
            break
        I = r['value']
        count += 1
        
        # Check second level
        data = HANDLERS['pdb_data']({'ns': ns, 'subs': [I]})
        code = data.get('value', 0)
        
        if code in (10, 11):  # has children
            print(f"  ^{ns}({I})  [$D={code}]")
            J = ''
            child_count = 0
            while child_count < 3:
                r2 = HANDLERS['pdb_order']({'ns': ns, 'subs': [I, J]})
                if not r2.get('value'):
                    break
                J = r2['value']
                child_count += 1
                v = HANDLERS['pdb_get']({'ns': ns, 'subs': [I, J]})
                val = v.get('value', 'NULL')
                print(f"    ({J}) = {str(val)[:40]}")
        elif code == 1:  # has value only
            v = HANDLERS['pdb_get']({'ns': ns, 'subs': [I]})
            val = v.get('value', 'NULL')
            print(f"  ^{ns}({I}) = {str(val)[:60]} [value only]")
    
    total = HANDLERS['pdb_query']({'sql': f"SELECT COUNT(*) as n FROM _globals WHERE ns='{ns}'"})
    total_n = total['rows'][0]['n'] if total.get('rows') else 0
    print(f"  ... {total_n} total nodes in ^{ns}")

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('cmd', choices=['SS','GL','GI'], nargs='?', default='SS')
    p.add_argument('ns', nargs='?')
    args = p.parse_args()
    
    if args.cmd == 'SS':
        pct_SS()
    elif args.cmd == 'GL':
        pct_GL(args.ns)
    elif args.cmd == 'GI':
        pct_GL(args.ns or 'CASITY')
