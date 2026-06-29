#!/usr/bin/env python3
"""
Repo Health Scanner — Benchmark v4 Artifact

Scans a repository directory and reports:
- Total size, file count, directory count
- Largest files (top 10)
- Duplicate files (by content hash)
- Files without extensions
- Missing markdown documentation in source directories

Uses LUMEN tools via direct import for zero-overhead scanning.

Usage: python repo_scanner.py [repo_path]
Default: ../../
"""

import os, sys, hashlib, json
from collections import defaultdict
from pathlib import Path


def scan_directory(root_path):
    """Walk directory and collect stats."""
    stats = {"files": 0, "dirs": 0, "total_size": 0, "largest": [], "no_ext": [], "duplicates": defaultdict(list)}
    
    for dirpath, dirnames, filenames in os.walk(root_path):
        # Skip .git, node_modules, __pycache__, .wrangler, dist, target
        dirnames[:] = [d for d in dirnames if d not in ('.git','node_modules','__pycache__','.wrangler','dist','target','.astro','.vscode','.github')]
        stats["dirs"] += len(dirnames)
        
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                size = os.path.getsize(fpath)
            except OSError:
                continue
            
            stats["files"] += 1
            stats["total_size"] += size
            stats["largest"].append((fpath, size))
            
            # No extension check
            if '.' not in fname:
                stats["no_ext"].append(fpath)
            
            # Hash small files for duplicate detection (<1MB)
            if size < 1_000_000:
                try:
                    with open(fpath, 'rb') as f:
                        h = hashlib.sha256(f.read()).hexdigest()
                    stats["duplicates"][h].append(fpath)
                except Exception:
                    pass
    
    # Sort largest
    stats["largest"].sort(key=lambda x: -x[1])
    return stats


def find_missing_docs(root_path):
    """Find directories with source code but no README/docs."""
    missing = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in ('.git','node_modules','__pycache__','.wrangler','dist','target','.astro')]
        
        has_source = any(f.endswith(('.py','.rs','.ts','.js','.cs','.php')) for f in filenames)
        has_doc = any(f.lower().startswith('readme') or f.lower().endswith('.md') for f in filenames)
        
        if has_source and not has_doc:
            missing.append(dirpath)
    
    return missing


def format_size(size_bytes):
    """Human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', '..')
    root = os.path.abspath(root)
    
    print(f"\n{'='*60}")
    print(f"  Repo Health Scanner — Benchmark v4")
    print(f"  Target: {root}")
    print(f"{'='*60}\n")
    
    stats = scan_directory(root)
    
    # Summary
    print(f"📊 Summary:")
    print(f"  Files: {stats['files']}")
    print(f"  Dirs:  {stats['dirs']}")
    print(f"  Size:  {format_size(stats['total_size'])}")
    
    # Largest files
    print(f"\n📦 Top 10 Largest:")
    for path, size in stats['largest'][:10]:
        print(f"  {format_size(size):>10s}  {os.path.relpath(path, root)}")
    
    # Duplicates
    dupes = {h: paths for h, paths in stats['duplicates'].items() if len(paths) > 1}
    if dupes:
        wasted = sum(os.path.getsize(paths[1]) for paths in dupes.values() for path in paths[1:])
        print(f"\n🔄 Duplicates: {len(dupes)} groups, {format_size(wasted)} wasted")
        for h, paths in list(dupes.items())[:5]:
            print(f"  {os.path.basename(paths[0])}: {len(paths)} copies")
    
    # No extension
    if stats['no_ext']:
        print(f"\n❓ Files without extension: {len(stats['no_ext'])}")
        for p in stats['no_ext'][:5]:
            print(f"  {os.path.relpath(p, root)}")
    
    # Missing docs
    missing = find_missing_docs(root)
    if missing:
        print(f"\n📝 Dirs with code but no README/docs: {len(missing)}")
        for p in missing[:10]:
            print(f"  {os.path.relpath(p, root)}")
    
    print(f"\n{'='*60}")
    print(f"  Scan complete.")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
