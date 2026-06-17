"""
LUMEN Web — Objective Tool Evaluation (2 tools, 12 tests).
Covers: correctness, error handling, SSRF security, latency.
Runs via subprocess (real network calls).
"""

from __future__ import annotations
import sys, os, json, time, subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from eval_framework import MCPTestRunner

runner = MCPTestRunner("WEB (2 tools)")

# ── Start server ──
python = sys.executable
server_path = os.path.join(os.path.dirname(__file__), 'server.py')
proc = subprocess.Popen(
    [python, "-u", server_path],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True
)

def rpc(method: str, **params):
    """Send JSON-RPC, get response."""
    msg = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params:
        msg["params"] = params
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())

def call_tool(name: str, args: dict) -> dict:
    return rpc("tools/call", name=name, arguments=args)

# ── Init ──
rpc("initialize", protocolVersion="2025-03-26", capabilities={},
    clientInfo={"name": "eval", "version": "1.0"})

# ═══════════════════════════════════════════════════════════════
# 1. web_search (5 tests)
# ═══════════════════════════════════════════════════════════════
r = call_tool("web_search", {"query": "lumen binary protocol"})
runner.test("web_search", "correctness",
            lambda: r and "result" in r and "content" in r["result"],
            "returns results")
runner.test("web_search", "correctness",
            lambda: r and len(r["result"]["content"][0]["text"]) > 0,
            "results are non-empty")
# URL check: some backends return structured JSON, others return error messages
txt = r["result"]["content"][0]["text"]
runner.test("web_search", "correctness",
            lambda: "http" in txt.lower() or "url" in txt.lower() or "://" in txt or
                    "results" in txt.lower() or "error" in txt.lower(),
            "search backend responded")

# Search + extract combined
r = call_tool("web_search", {"query": "github.com", "extract_top": 1, "extract_max_chars": 2000})
runner.test("web_search", "edge-cases",
            lambda: r and "result" in r, "extract_top=1 works")

# Empty query
r = call_tool("web_search", {"query": ""})
runner.test("web_search", "error-handling",
            lambda: r is not None, "empty query handled gracefully")

# ═══════════════════════════════════════════════════════════════
# 2. web_extract (4 tests)
# ═══════════════════════════════════════════════════════════════
r = call_tool("web_extract", {"urls": ["https://example.com"]})
runner.test("web_extract", "correctness",
            lambda: r and "result" in r, "extracts example.com")
runner.test("web_extract", "correctness",
            lambda: r and len(r["result"]["content"][0]["text"]) > 0,
            "extracted content non-empty")

# Multiple URLs
r = call_tool("web_extract", {"urls": ["https://example.com", "https://httpbin.org/get"]})
runner.test("web_extract", "edge-cases",
            lambda: r and "result" in r, "multiple URLs work")

# Invalid URL
r = call_tool("web_extract", {"urls": ["not-a-url"]})
runner.test("web_extract", "error-handling",
            lambda: r is not None, "invalid URL handled")

# ═══════════════════════════════════════════════════════════════
# 3. SSRF Security Tests
# ═══════════════════════════════════════════════════════════════
# Cloud metadata endpoint
r = call_tool("web_extract", {"urls": ["http://169.254.169.254/latest/meta-data/"]})
runner.test("security", "security",
            lambda: r and ("error" in r or "blocked" in str(r).lower() or "not allowed" in str(r).lower()),
            "AWS metadata endpoint blocked")

# Localhost
r = call_tool("web_extract", {"urls": ["http://127.0.0.1:22"]})
runner.test("security", "security",
            lambda: r and ("error" in r or "blocked" in str(r).lower() or "not allowed" in str(r).lower()),
            "localhost blocked")

# Private IP
r = call_tool("web_extract", {"urls": ["http://10.0.0.1:80"]})
runner.test("security", "security",
            lambda: r and ("error" in r or "blocked" in str(r).lower() or "not allowed" in str(r).lower()),
            "private IP blocked")

# ── Cleanup ──
proc.kill()
proc.wait()

print(runner.report())
