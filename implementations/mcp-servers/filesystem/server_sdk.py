#!/usr/bin/env python3
"""
LUMEN Filesystem MCP Server — file ops via LUMEN binary transport.

Uses the LumenServer SDK.  The same tool logic as the full
shared_tools.py version, but 80% less boilerplate.

Usage:
    python server.py
    hermes mcp add lumen-fs --command python --args server.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lumen_server import LumenServer

server = LumenServer("lumen-filesystem", version="1.0.0")

# ── Tools ────────────────────────────────────────────────────────────────────

@server.tool("read_file", description="Read a text file with line numbers and pagination")
def read_file(path: str, offset: int = 1, limit: int = 500) -> str:
    """Read a file with optional offset/limit."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        # Suggest similar filenames
        parent = p.parent
        if parent.exists():
            similar = [f.name for f in parent.iterdir() if f.is_file()][:5]
            hint = f"\nSimilar files in {parent}: {', '.join(similar)}" if similar else ""
        else:
            hint = ""
        return f"File not found: {path}{hint}"
    if not p.is_file():
        return f"Not a file: {path}"

    lines = p.read_text(encoding="utf-8", errors="replace").split("\n")
    total = len(lines)
    start = max(1, min(offset, total))
    end = min(start + limit - 1, total)

    out = []
    for i in range(start - 1, end):
        out.append(f"{i + 1}|{lines[i]}")
    if end < total:
        out.append(f"... ({total - end} more lines, use offset={end + 1})")
    return "\n".join(out)


@server.tool("write_file", description="Write content to a file, replacing existing content")
def write_file(path: str, content: str) -> str:
    """Write content to a file, creating parent directories."""
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Written {len(content)} bytes to {p}"


@server.tool("search_files", description="Search file contents (regex) or find files by name (glob)")
def search_files(
    pattern: str,
    target: str = "content",
    path: str = ".",
    file_glob: str = "",
    limit: int = 50,
    output_mode: str = "content",
) -> str:
    """Search file contents with regex or find files by glob pattern."""
    import re
    import fnmatch

    root = Path(path).expanduser().resolve()
    if not root.exists():
        return f"Directory not found: {path}"

    if target == "files":
        matches = []
        for f in root.rglob("*"):
            if f.is_file() and fnmatch.fnmatch(f.name, pattern):
                matches.append(str(f))
                if len(matches) >= limit:
                    break
        return "\n".join(matches[:limit]) if matches else f"No files matching '{pattern}'"

    # Content search
    regex = re.compile(pattern.encode() if isinstance(pattern, bytes) else pattern)
    results = []
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        if file_glob and not fnmatch.fnmatch(f.name, file_glob):
            continue
        try:
            content = f.read_bytes()
            for lineno, line in enumerate(content.split(b"\n"), 1):
                if regex.search(line):
                    results.append(f"{f}:{lineno}: {line.decode('utf-8', errors='replace')[:120]}")
                    if len(results) >= limit:
                        break
        except Exception:
            continue
        if len(results) >= limit:
            break

    return "\n".join(results) if results else "No matches found"


if __name__ == "__main__":
    server.run()
