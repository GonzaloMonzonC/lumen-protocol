#!/usr/bin/env python3
"""Regression test for EB fixes: cache invalidation + exact metadata + IVF removed.
Runs against a TEMP PDB (PDB_PATH env) — never touches the real database."""
import os, sys, tempfile

os.environ["PDB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_eb.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdb_tools as pt

fails = []
def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL"), name, detail)
    if not cond:
        fails.append(name)

# 1. Embed 2 texts (one SHORT text + custom source — heuristic would have lost both)
r1 = pt.tool_embed({"texts": ["El gato duerme en el sofa azul",
                              "Protocolo de sincronizacion DDP entre edge y local"],
                    "source": "test-corto"})
check("embed first batch", r1.get("count") == 2, str(r1))

# 2. Search → cold matrix load, metadata must resolve text+source exactly
s1 = pt.tool_embed_search({"query": "gato sofa dormir", "limit": 5})
hit = next((x for x in s1["results"] if "gato" in x["text"]), None)
check("metadata text (short text rescued)", hit is not None and hit["text"] == "El gato duerme en el sofa azul",
      str([(x["text"], x["source"]) for x in s1["results"]]))
check("metadata source (non-petmap rescued)", hit is not None and hit["source"] == "test-corto",
      str([(x["text"], x["source"]) for x in s1["results"]]))

# 3. Embed NEW text AFTER matrix cache loaded → stale-cache fix
pt.tool_embed({"texts": ["lasana con tomate y albahaca fresca"], "source": "recetas"})
s2 = pt.tool_embed_search({"query": "comida italiana lasana", "limit": 5})
check("cache invalidated after embed (new doc found)",
      any("lasana" in x["text"] for x in s2["results"]),
      str([(x["text"][:30], round(x["score"], 3)) for x in s2["results"]]))

# 4. Re-embed identical text (dedup) → still searchable, no crash
pt.tool_embed({"texts": ["lasana con tomate y albahaca fresca"], "source": "recetas"})
s3 = pt.tool_embed_search({"query": "albahaca fresca", "limit": 3})
check("dedup re-embed keeps index consistent",
      any("lasana" in x["text"] for x in s3["results"]),
      str([(x["text"][:30], x["source"]) for x in s3["results"]]))

# 5. No EMBED_IVF rows written anymore (dead writes removed)
import sqlite3
conn = sqlite3.connect(os.environ["PDB_PATH"])
ivf = conn.execute("SELECT COUNT(*) FROM _globals WHERE ns='EMBED_IVF'").fetchone()[0]
vec = conn.execute("SELECT COUNT(*) FROM _globals WHERE ns='EMBED_VEC'").fetchone()[0]
check("no EMBED_IVF writes", ivf == 0, f"ivf={ivf}")
check("EMBED_VEC written", vec == 3, f"vec={vec}")

print()
print("RESULT:", "ALL PASS ✅" if not fails else f"FAILURES: {fails}")
sys.exit(1 if fails else 0)
