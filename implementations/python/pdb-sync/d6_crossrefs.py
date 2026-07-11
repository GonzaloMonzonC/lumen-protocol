def doc_add_link(ns: str, subs: list, target: str) -> dict:
    """Añadir un cross-ref a un documento. 
    target: \"^decisions:1\", \"^learnings:42\"
    Mantiene índice inverso automático en ^docs(\"refs\", target)."""
    from pdb_docs import doc_get, doc_set
    from pdb_tools import tool_set, tool_get
    doc = doc_get(ns, subs, execute=False)
    if not doc: return {\"success\": False, \"error\": \"doc not found\"}
    links = doc.get(\"links\", [])
    if target not in links: links.append(target)
    doc[\"links\"] = links
    result = doc_set(ns, subs, doc)
    doc_path = f\"docs/{ns}/{'/'.join(str(s) for s in subs)}\"
    refs = tool_get({\"ns\": \"docs\", \"subs\": [\"refs\", target]})
    existing = refs.get(\"value\") if refs.get(\"success\") else []
    if doc_path not in existing: existing.append(doc_path)
    tool_set({\"ns\": \"docs\", \"subs\": [\"refs\", target], \"value\": existing})
    return result

def doc_find_refs(target: str, limit: int = 20) -> list:
    \"\"\"Encontrar todos los docs que referencian un target.
    Usa índice inverso ^docs(\"refs\", target) para <10ms.\"\"\"
    from pdb_tools import tool_get
    refs = tool_get({\"ns\": \"docs\", \"subs\": [\"refs\", target]})
    if refs.get(\"success\") and refs.get(\"value\"):
        return [{\"doc\": p, \"target\": target} for p in refs[\"value\"][:limit]]
    return []

def doc_graph(center_ns: str, center_subs: list, depth: int = 1) -> dict:
    \"\"\"Grafo de referencias desde un doc central.\"\"\"
    from pdb_docs import doc_get
    doc = doc_get(center_ns, center_subs, execute=False)
    if not doc: return {\"error\": \"doc not found\"}
    doc_path = f\"docs/{center_ns}/{'/'.join(str(s) for s in center_subs)}\"
    links_out = doc.get(\"links\", [])
    links_in = []
    for link in links_out:
        refs = doc_find_refs(link, limit=10)
        for r in refs:
            if r[\"doc\"] not in links_in: links_in.append(r[\"doc\"])
    return {\"center\": doc_path, \"links_out\": links_out, \"links_in\": links_in,
            \"stats\": {\"out\": len(links_out), \"in\": len(links_in)}}
