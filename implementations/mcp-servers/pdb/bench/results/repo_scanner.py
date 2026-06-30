#!/usr/bin/env python3
"""
LUMEN Repo Health Scanner v4
Scans a repository for: largest files, duplicates, missing docs, no-extension files.
Results stored in PDB ^REPO_SCAN namespace.
"""

import os
import sys
import hashlib
from pathlib import Path
from collections import defaultdict

# Add PDB tools to path
PDB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pdb_tools.py")
sys.path.insert(0, PDB_DIR)


def sha256_file(filepath):
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
    except (IOError, PermissionError):
        return None
    return h.hexdigest()


def scan_repo(repo_path):
    """Scan repository and return structured results."""
    results = {
        "repo_path": str(repo_path),
        "total_files": 0,
        "total_size": 0,
        "largest_files": [],
        "duplicates": {},
        "no_extension": [],
        "missing_docs": [],
        "by_extension": defaultdict(int),
    }

    for root, dirs, files in os.walk(repo_path):
        # Skip .git
        if ".git" in root or any("node_modules" in d for d in dirs):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules")]
            continue

        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                stat = os.stat(fpath)
                size = stat.st_size
                ext = os.path.splitext(fname)[1].lower()
                rel = os.path.relpath(fpath, repo_path)

                results["total_files"] += 1
                results["total_size"] += size
                results["by_extension"][ext or "(no extension)"] += 1

                # Track largest files (top 20)
                results["largest_files"].append((size, rel))

                # Track no-extension files
                if not ext:
                    results["no_extension"].append(rel)

                # Track missing docs (source files without .md companion)
                if ext in (".py", ".ts", ".js", ".rs", ".go") and not fname.startswith("test"):
                    companion = os.path.splitext(rel)[0] + ".md"
                    if not os.path.exists(os.path.join(repo_path, companion)):
                        results["missing_docs"].append(rel)

                # Track duplicates via SHA-256
                fhash = sha256_file(fpath)
                if fhash:
                    if fhash in results["duplicates"]:
                        results["duplicates"][fhash]["files"].append(rel)
                    else:
                        results["duplicates"][fhash] = {"size": size, "files": [rel]}

            except OSError:
                continue

    # Sort and trim
    results["largest_files"].sort(reverse=True)
    results["largest_files"] = results["largest_files"][:20]

    # Filter duplicates to only groups with 2+ files
    results["duplicates"] = {
        k: v for k, v in results["duplicates"].items() if len(v["files"]) > 1
    }

    return results


def format_size(size_bytes):
    """Format bytes to human-readable."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


if __name__ == "__main__":
    # Default to lumen-protocol repo
    repo = Path(__file__).resolve().parent.parent.parent.parent.parent.parent / "Documents" / "GitHub" / "lumen-protocol"
    if not repo.exists():
        repo = Path(".").resolve()

    results = scan_repo(repo)

    print("=" * 60)
    print("LUMEN REPO HEALTH SCAN REPORT")
    print("=" * 60)
    print(f"Repository: {results['repo_path']}")
    print(f"Total files: {results['total_files']}")
    print(f"Total size: {format_size(results['total_size'])} ({results['total_size']} bytes)")
    print()

    print("--- LARGEST FILES (top 10) ---")
    for size, path in results["largest_files"][:10]:
        print(f"  {format_size(size):>10}  {path}")
    print()

    print(f"--- DUPLICATES: {len(results['duplicates'])} groups ---")
    total_wasted = 0
    for h, info in list(results["duplicates"].items())[:10]:
        wasted = info["size"] * (len(info["files"]) - 1)
        total_wasted += wasted
        print(f"  [{format_size(info['size'])}] x{len(info['files'])}: {info['files'][0]}")
        for f in info["files"][1:3]:
            print(f"    -> {f}")
    print(f"  Total wasted: {format_size(total_wasted)}")
    print()

    print(f"--- FILES WITHOUT EXTENSION: {len(results['no_extension'])} ---")
    for f in results["no_extension"][:10]:
        print(f"  {f}")
    print()

    print(f"--- MISSING DOCS: {len(results['missing_docs'])} ---")
    for f in results["missing_docs"][:10]:
        print(f"  {f}")
    print()

    print("--- EXTENSION BREAKDOWN ---")
    for ext, count in sorted(results["by_extension"].items(), key=lambda x: -x[1])[:15]:
        print(f"  {ext or '(none)':>20}  {count:5} files")
