#!/usr/bin/env python3
"""
pdb-docs-git-hook — Post-commit hook para PDB Doc Engine.

Detecta archivos modificados en un commit y actualiza los documentos
en ^docs que referencian esos archivos. Si un doc es de tipo "code"
(TTL=0), lo marca como stale automáticamente.

Instalación:
    cp pdb_docs_git_hook.py .git/hooks/post-commit
    chmod +x .git/hooks/post-commit

O para todos los repos:
    python pdb_docs_git_hook.py --install ~/Documents/GitHub/lumen-protocol

Author: Hermes + CadencesLab (D4 — PDB Doc Engine)
Date: 2026-07-11
License: MIT (lumen-protocol)
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Añadir el directorio de pdb-sync al path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from pdb_docs import doc_get, doc_set, doc_search, doc_list, DOCS_NAMESPACE

# ── Git helpers ─────────────────────────────────────────────────────

def get_changed_files():
    """Obtener archivos modificados en el último commit."""
    try:
        result = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
            capture_output=True, text=True, timeout=5
        )
        return [f.strip() for f in result.stdout.split("\n") if f.strip()]
    except Exception:
        return []

def get_commit_hash():
    """Obtener hash del último commit."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip()
    except Exception:
        return None

def get_repo_name():
    """Obtener nombre del repo desde el remoto."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5
        )
        url = result.stdout.strip()
        # Extraer nombre del repo de la URL
        return url.split("/")[-1].replace(".git", "")
    except Exception:
        return Path.cwd().name

# ── Doc matching ─────────────────────────────────────────────────────

def find_docs_for_file(filename: str) -> list:
    """Buscar documentos en ^docs que referencien un archivo."""
    # Buscar por nombre de archivo en content
    results = doc_search(filename, limit=20)
    matching = []
    for r in results:
        doc_ns = r.get("key", "").split("/")[0] if "/" in r.get("key", "") else r.get("key", "")
        doc_path = r.get("key", "").split("/")[1:] if "/" in r.get("key", "") else []
        if doc_ns and doc_path:
            doc = doc_get(doc_ns, doc_path)
            if doc:
                matching.append((doc_ns, doc_path, doc))
    return matching

def update_doc_for_commit(ns: str, subs: list, doc: dict, commit_hash: str):
    """Actualizar metadatos de un doc tras un commit."""
    doc["last_commit"] = commit_hash
    doc["last_commit_at"] = subprocess.run(
        ["git", "log", "-1", "--format=%aI", commit_hash],
        capture_output=True, text=True
    ).stdout.strip() or "unknown"

    # Si es code doc (TTL=0), marcar como revisado, no stale
    # (el commit es la actualización)
    if ns == "code":
        doc["stale"] = False
        doc["confidence"] = min(10, doc.get("confidence", 5) + 1)  # boost confidence

    return doc_set(ns, subs, doc)

# ── Main hook ────────────────────────────────────────────────────────

def run_hook():
    """Ejecutar el hook post-commit."""
    repo = get_repo_name()
    commit = get_commit_hash()
    if not commit:
        print("[pdb-docs-hook] No commit hash, skipping")
        return

    files = get_changed_files()
    if not files:
        print("[pdb-docs-hook] No files changed")
        return

    print(f"[pdb-docs-hook] Repo: {repo}, Commit: {commit}, Files: {len(files)}")

    updated = 0
    for f in files:
        docs = find_docs_for_file(f)
        for ns, subs, doc in docs:
            result = update_doc_for_commit(ns, subs, doc, commit)
            if result.get("success"):
                updated += 1
                doc_path = f"docs/{ns}/{'/'.join(str(s) for s in subs)}"
                print(f"  ✅ {doc_path} → commit {commit}")

    print(f"[pdb-docs-hook] Updated {updated} docs")

def install_hook(repo_path: str):
    """Instalar el hook en un repositorio."""
    hook_path = Path(repo_path) / ".git" / "hooks" / "post-commit"
    script_path = Path(__file__).resolve()

    # Crear symlink o copiar
    if os.name == "nt":  # Windows
        with open(hook_path, "w") as f:
            f.write(f'#!/bin/sh\npython "{script_path}"\n')
    else:
        if hook_path.exists():
            hook_path.unlink()
        hook_path.symlink_to(script_path)
        hook_path.chmod(0o755)

    print(f"[pdb-docs-hook] Installed in {hook_path}")

# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--install":
        repo = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
        install_hook(repo)
    else:
        run_hook()
