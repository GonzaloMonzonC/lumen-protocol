#!/usr/bin/env python3
"""
fuzzy_search.py — Fuzzy file search tools for LLM agents.

Filename and content search with fuzzy matching, ranking, and caching.
No external dependencies — uses difflib and pure Python.

PDB schema:
  FUZZY_CACHE: ns='FUZZY_CACHE', subkey=f'{base_path}:{mtime}' → json of {files, indexed_at}
"""

import json
import os
import sqlite3
import time
import difflib
from pathlib import Path
from typing import Optional

HERE = Path(__file__).parent
_PDB_PATH = HERE.parent / "pdb" / "lumen-pdb.db"

MAX_CACHE_AGE = 300  # 5 min cache TTL


def _get_conn():
    return sqlite3.connect(str(_PDB_PATH))


def _lev_ratio(a: str, b: str) -> float:
    """Normalized similarity ratio (0-1) using difflib SequenceMatcher."""
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _walk_files(base_path: str, max_files: int = 5000) -> list[dict]:
    """Walk directory tree, return list of {path, name, dir, size}."""
    result = []
    base = Path(base_path).resolve()
    try:
        for root, dirs, files in os.walk(str(base)):
            if len(result) >= max_files:
                break
            for fname in files:
                if len(result) >= max_files:
                    break
                full = Path(root) / fname
                try:
                    stat = full.stat()
                    result.append({
                        "path": full.as_posix(),
                        "name": fname,
                        "dir": Path(root).as_posix(),
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    })
                except OSError:
                    continue
    except Exception:
        pass
    return result


def _score_filename(query: str, filename: str) -> float:
    """Score a filename against a fuzzy query. Returns 0-1 score."""
    q = query.lower()
    f = filename.lower()
    
    if q == f:
        return 1.0
    if q in f:
        # Bonus for exact substring match, weighted by position
        idx = f.index(q)
        return 0.85 + 0.1 * (1 - idx / max(len(f), 1))
    
    # Check if query words appear in filename
    q_words = q.split()
    if len(q_words) > 1:
        matching = sum(1 for w in q_words if w in f)
        if matching == len(q_words):
            return 0.8
        return 0.4 * matching / len(q_words)
    
    # Levenshtein ratio
    return _lev_ratio(q, f)


def tool_search_files_fuzzy(query: str, path: str = ".", limit: int = 10) -> dict:
    """Fuzzy search files by name. No regex needed — tolerates typos and partial names."""
    query = query.strip()
    if not query:
        return {"content": [{"type": "text", "text": "Query required."}]}
    
    files = _walk_files(path)
    if not files:
        return {"content": [{"type": "text", "text": f"No files found under: {path}"}]}
    
    # Score and rank
    scored = []
    for f in files:
        score = _score_filename(query, f["name"])
        if score > 0.2:  # threshold
            scored.append((score, f))
    
    scored.sort(key=lambda x: -x[0])
    top = scored[:limit]
    
    if not top:
        return {"content": [{"type": "text", "text": f"No matches for '{query}' under {path}. Try a different query."}]}
    
    lines = [f"Fuzzy search '{query}' ({len(top)} results):"]
    for score, f in top:
        pct = round(score * 100)
        lines.append(f"  [{pct:02d}%] {f['dir']}/{f['name']}  ({f['size']} bytes)")
    
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_search_files_content_fuzzy(query: str, path: str = ".", limit: int = 10, max_size: int = 102400) -> dict:
    """Fuzzy search file contents. Reads text files and matches for query words.
    Skips binary files and files larger than max_size bytes."""
    query = query.strip()
    if not query:
        return {"content": [{"type": "text", "text": "Query required."}]}
    
    files = _walk_files(path, max_files=1000)
    
    # Text extensions to check
    text_exts = {'.py', '.js', '.ts', '.jsx', '.tsx', '.json', '.yaml', '.yml', 
                 '.md', '.txt', '.html', '.css', '.scss', '.cfg', '.ini', '.conf',
                 '.toml', '.xml', '.sh', '.bash', '.env', '.sql', '.rs', '.go',
                 '.java', '.rb', '.php', '.vue', '.svelte', '.lock', '.gitignore'}
    
    q_lower = query.lower()
    q_words = q_lower.split()
    
    results = []
    for f in files:
        if len(results) >= limit:
            break
        if f["size"] > max_size:
            continue
        ext = Path(f["name"]).suffix.lower()
        if ext and ext not in text_exts:
            continue
        if f["size"] == 0:
            continue
        
        try:
            with open(f["path"], 'r', encoding='utf-8', errors='ignore') as fp:
                content = fp.read(4096)  # Read first 4K for speed
        except Exception:
            continue
        
        content_lower = content.lower()
        
        # Score: how many query words appear in content
        if q_lower in content_lower:
            score = 1.0
        elif len(q_words) > 1:
            matching = sum(1 for w in q_words if w in content_lower)
            if matching == 0:
                continue
            score = 0.5 * matching / len(q_words)
        else:
            score = 0.5 if q_words[0] in content_lower else 0
        
        if score > 0:
            # Find context snippet
            idx = content_lower.find(q_words[0]) if q_words else 0
            start = max(0, idx - 40)
            end = min(len(content), idx + 100)
            snippet = content[start:end].replace('\n', '↵')
            if start > 0:
                snippet = "..." + snippet
            if end < len(content):
                snippet = snippet + "..."
            
            results.append((score, f["path"], snippet))
    
    results.sort(key=lambda x: -x[0])
    top = results[:limit]
    
    if not top:
        return {"content": [{"type": "text", "text": f"No content matches for '{query}' under {path}."}]}
    
    lines = [f"Content fuzzy search '{query}' ({len(top)} results):"]
    for score, fpath, snippet in top:
        pct = round(score * 100)
        lines.append(f"\n  [{pct:02d}%] {fpath}")
        lines.append(f"         {snippet[:120]}")
    
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


FUZZY_SEARCH_SCHEMAS = [
    {
        "name": "search_files_fuzzy",
        "description": "Fuzzy search files by name. Tolerates typos, partial names, and word fragments. No regex needed. Returns top N matches ranked by similarity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Fuzzy search query (e.g. 'serv py', 'think ser', 'pdb_watch')"},
                "path": {"type": "string", "description": "Directory to search (default: current dir)"},
                "limit": {"type": "integer", "description": "Max results (default: 10)", "default": 10}
            },
            "required": ["query"]
        }
    },
    {
        "name": "search_files_content_fuzzy",
        "description": "Fuzzy search text file contents. Matches query words in file content, returns ranked results with context snippets. Skips binary files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (words to find in file contents)"},
                "path": {"type": "string", "description": "Directory to search (default: current dir)"},
                "limit": {"type": "integer", "description": "Max results (default: 10)", "default": 10}
            },
            "required": ["query"]
        }
    }
]

FUZZY_SEARCH_HANDLERS = {
    "search_files_fuzzy": tool_search_files_fuzzy,
    "search_files_content_fuzzy": tool_search_files_content_fuzzy,
}
