"""PDB Cognitive Benchmark — fresh subprocess, no lock issues"""
import sys, os, tempfile, time, sqlite3
from pathlib import Path

def main():
    tmpdir = tempfile.mkdtemp()
    pdb_path = os.path.join(tmpdir, "p.db")
    sql_path = os.path.join(tmpdir, "s.db")
    
    os.environ['PDB_PATH'] = pdb_path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    # Force fresh import by clearing any cached module
    for m in list(sys.modules.keys()):
        if 'pdb_tools' in m:
            del sys.modules[m]
    
    import pdb_tools
    from m_light import MEvaluator
    
    N = 3000
    
    print("=" * 55)
    print("  🧪 PDB COGNITIVE BENCHMARK")
    print("=" * 55)
    
    # 1. INSERT
    t0 = time.time()
    for i in range(N):
        pdb_tools.tool_set({"ns": "B", "subs": [i], "value": f"v_{i}"})
    pdb_ins = time.time() - t0
    print(f"\n📥 Insert {N} records")
    print(f"   PDB: {N/pdb_ins:.0f} ops/s")
    
    conn = sqlite3.connect(sql_path)
    conn.execute("CREATE TABLE b (id INT PRIMARY KEY, val TEXT)")
    t0 = time.time()
    for i in range(N):
        conn.execute("INSERT OR REPLACE INTO b VALUES (?,?)", [i, f"v_{i}"])
    conn.commit()
    sql_ins = time.time() - t0
    print(f"   SQL: {N/sql_ins:.0f} ops/s")
    r1 = round(pdb_ins / sql_ins, 2)
    print(f"   Ratio: {r1}x {'✅' if r1 <= 1 else ''}")
    
    # 2. ORDER vs SQL SCAN
    c, cur = 0, ""
    t0 = time.time()
    for _ in range(N):
        r = pdb_tools.tool_order({"ns": "B", "subs": [cur], "direction": 1})
        if r.get("value") is None:
            break
        cur = r["value"]
        c += 1
    pdo = time.time() - t0
    print(f"\n🔍 Traverse {c} items")
    print(f"   \$ORDER: {c/pdo:.0f} items/s")
    
    t0 = time.time()
    rows = conn.execute("SELECT id FROM b ORDER BY id").fetchall()
    sql_scan = time.time() - t0
    print(f"   SQL: {len(rows)/sql_scan:.0f} items/s")
    r2 = round(pdo / sql_scan, 2)
    print(f"   Ratio: {r2}x {'✅' if r2 <= 1 else ''}")
    
    # 3. SINGLE GET
    t0 = time.time()
    for _ in range(1000):
        pdb_tools.tool_get({"ns": "B", "subs": [42]})
    pdb_get = (time.time() - t0) * 1000 / 1000
    t0 = time.time()
    for _ in range(1000):
        conn.execute("SELECT val FROM b WHERE id=42").fetchone()
    sql_get = (time.time() - t0) * 1000 / 1000
    print(f"\n⚡ Single GET ({1000}x)")
    print(f"   \$GET: {pdb_get:.4f} ms")
    print(f"   SQL:  {sql_get:.4f} ms")
    r3 = round(pdb_get / sql_get, 2)
    print(f"   Ratio: {r3}x {'✅' if r3 <= 1 else ''}")
    
    # 4. HIERARCHICAL
    t0 = time.time()
    for p in range(100):
        pdb_tools.tool_set({"ns": "P", "subs": [p, "name"], "value": f"P{p}"})
        for v in range(10):
            pdb_tools.tool_set({"ns": "P", "subs": [p, "v", v], "value": f"V{v}"})
    pdb_hier = time.time() - t0
    
    conn.execute("CREATE TABLE p (p INT, v INT, val TEXT)")
    t0 = time.time()
    for p in range(100):
        conn.execute("INSERT INTO p VALUES (?,?,?)", [p, 0, f"P{p}"])
        for v in range(10):
            conn.execute("INSERT INTO p VALUES (?,?,?)", [p, v, f"V{v}"])
    conn.commit()
    sql_hier = time.time() - t0
    print(f"\n🌳 Hierarchical (100x10)")
    print(f"   PDB: {pdb_hier:.3f}s")
    print(f"   SQL: {sql_hier:.3f}s")
    r4 = round(pdb_hier / sql_hier, 2)
    print(f"   Ratio: {r4}x {'✅' if r4 <= 1 else ''}")
    
    # 5. M-LIGHT
    m = MEvaluator(pdb_tools)
    t0 = time.time()
    for _ in range(50):
        m2 = MEvaluator(pdb_tools)
        m2.eval('S I="" F  S I=$O(^B(I)) Q:I=""')
    ml_time = (time.time() - t0) / 50
    
    t0 = time.time()
    for _ in range(50):
        conn.execute("SELECT id FROM b ORDER BY id").fetchall()
    sql_it = (time.time() - t0) / 50
    print(f"\n🧠 M-Light \$ORDER ({50}x)")
    print(f"   M-Light: {ml_time*1000:.3f} ms")
    print(f"   SQL:     {sql_it*1000:.3f} ms")
    r5 = round(ml_time / sql_it, 2)
    print(f"   Ratio: {r5}x {'✅' if r5 <= 1 else ''}")
    
    # SUMMARY
    ratios = [r1, r2, r3, r4, r5]
    print(f"\n{'='*55}")
    print("  📊 KPI SUMMARY")
    print(f"{'='*55}")
    print(f"   Insert:        {r1}x {'✅' if r1 <= 1 else '⚠️'}")
    print(f"   \$ORDER:        {r2}x {'✅' if r2 <= 1 else '⚠️'}")
    print(f"   \$GET latency:  {r3}x {'✅' if r3 <= 1 else '⚠️'}")
    print(f"   Hierarchical:  {r4}x {'✅' if r4 <= 1 else '⚠️'}")
    print(f"   M-Light:       {r5}x {'✅' if r5 <= 1 else '⚠️'}")
    
    avg = sum(ratios) / len(ratios)
    print(f"\n   📈 Overall: {avg:.2f}x")
    if avg < 1:
        print("   🏆 PDB + M-Light > SQL en este benchmark")
    elif avg < 2:
        print("   ✅ PDB + M-Light = competitivo con SQL")
    else:
        print("   ⚠️ SQL mejor en rendimiento puro, pero PDB ofrece más")
    print("\n   La diferencia real: $ORDER es navegación jerárquica determinista,")
    print("   no una query plana. M-Light ejecuta código M contra los datos.")
    print("   Esto es un nuevo paradigma: MUMPS + LLM = cognición híbrida.")
    
    # Cleanup
    conn.close()
    pdb_tools._conn.close()
    for f in os.listdir(tmpdir):
        try: os.unlink(os.path.join(tmpdir, f))
        except: pass
    os.rmdir(tmpdir)
    
    # Save to wiki
    return {"ratios": ratios, "avg": avg}

if __name__ == '__main__':
    main()
