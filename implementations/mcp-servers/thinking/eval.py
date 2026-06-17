"""
LUMEN Thinking — Objective Tool Evaluation (10 tools, 26 tests).
Covers: chain operations, similarity, contradiction, summarize, plan,
        evaluate, bridge, assumptions, model, edge cases, stress.
Runs via subprocess (JSON-RPC).
"""

from __future__ import annotations
import sys, os, json, time, subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from eval_framework import MCPTestRunner

runner = MCPTestRunner("THINKING (10 tools)")

python = sys.executable
server = os.path.join(os.path.dirname(__file__), 'server.py')
proc = subprocess.Popen(
    [python, "-u", server],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True
)

def rpc(method: str, **params):
    msg = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params: msg["params"] = params
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())

def call_tool(name: str, args: dict) -> dict:
    return rpc("tools/call", name=name, arguments=args)

def ok(r): return r and "result" in r and "error" not in r
def text(r): return r.get("result", {}).get("content", [{}])[0].get("text", "")
def cid(r): return r.get("result", {}).get("chainId")

# ── Init ──
rpc("initialize", protocolVersion="2025-03-26", capabilities={},
    clientInfo={"name": "eval", "version": "1.0"})

# ═══════════════════════════════════════════════════════════════
# 1. sequential_thinking (5 tests)
# ═══════════════════════════════════════════════════════════════
r = call_tool("sequential_thinking", {"thought": "Step 1: analyze requirements",
    "thoughtNumber": 1, "totalThoughts": 5, "nextThoughtNeeded": True})
cid1 = cid(r)
runner.test("sequential_thinking", "correctness", lambda: ok(r), "creates first thought")
runner.test("sequential_thinking", "correctness",
            lambda: cid1 and cid1.startswith("chain_"), "auto chain ID")
runner.test("sequential_thinking", "correctness",
            lambda: r["result"]["thoughtCount"] == 1, "thought count correct")

r = call_tool("sequential_thinking", {"thought": "Step 2: design solution",
    "thoughtNumber": 2, "totalThoughts": 5, "nextThoughtNeeded": True, "chainId": cid1})
runner.test("sequential_thinking", "correctness",
            lambda: ok(r) and r["result"]["thoughtCount"] == 2, "chain continuation")

# Auto-numbering
r = call_tool("sequential_thinking", {"thought": "Auto numbered",
    "totalThoughts": 1, "nextThoughtNeeded": False})
runner.test("sequential_thinking", "edge-cases",
            lambda: cid(r) is not None, "auto-numbering works")

# ═══════════════════════════════════════════════════════════════
# 2. Revisions & branching (2 tests)
# ═══════════════════════════════════════════════════════════════
r = call_tool("sequential_thinking", {"thought": "REVISED: missed edge case",
    "thoughtNumber": 3, "totalThoughts": 5, "nextThoughtNeeded": True,
    "chainId": cid1, "isRevision": True, "revisesThought": 1})
runner.test("sequential_thinking", "edge-cases",
            lambda: ok(r) and "Revision" in text(r), "revision recorded")

r = call_tool("sequential_thinking", {"thought": "ALTERNATIVE: approach B",
    "thoughtNumber": 4, "totalThoughts": 5, "nextThoughtNeeded": True,
    "chainId": cid1, "branchFromThought": 2, "branchId": "alt-b"})
runner.test("sequential_thinking", "edge-cases",
            lambda: ok(r) and "Branch" in text(r), "branch recorded")

# ═══════════════════════════════════════════════════════════════
# 3. thought_similarity (3 tests)
# ═══════════════════════════════════════════════════════════════
r = call_tool("thought_similarity", {"chainId": cid1, "thought": "analyze requirements"})
runner.test("thought_similarity", "correctness", lambda: ok(r), "finds similar thoughts")
runner.test("thought_similarity", "correctness",
            lambda: "%" in text(r) or "similar" in text(r).lower(), "shows similarity metrics")

r = call_tool("thought_similarity", {"chainId": cid1, "thought": "banana pineapple orange", "minScore": 0.8})
runner.test("thought_similarity", "edge-cases",
            lambda: ok(r) and ("No similar" in text(r) or "0 similar" in text(r) or "none" in text(r).lower()),
            "high threshold returns empty for unrelated")

# ═══════════════════════════════════════════════════════════════
# 4. thought_contradiction (2 tests)
# ═══════════════════════════════════════════════════════════════
r = call_tool("thought_contradiction", {"chainId": cid1, "thought": "analysis is wrong and incorrect"})
runner.test("thought_contradiction", "correctness", lambda: ok(r), "contradiction check works")

# Consistent chain test
r2 = call_tool("sequential_thinking", {"thought": "The plan is solid and well-tested",
    "thoughtNumber": 1, "totalThoughts": 2, "nextThoughtNeeded": True})
cid2 = cid(r2)
call_tool("sequential_thinking", {"thought": "Tests all pass consistently",
    "thoughtNumber": 2, "totalThoughts": 2, "nextThoughtNeeded": False, "chainId": cid2})
r = call_tool("thought_contradiction", {"chainId": cid2, "thought": "plan and tests"})
runner.test("thought_contradiction", "edge-cases",
            lambda: ok(r) and ("No contradictions" in text(r) or "0 contradiction" in text(r).lower()),
            "consistent chain: no contradictions")

# ═══════════════════════════════════════════════════════════════
# 5. thought_summarize (2 tests)
# ═══════════════════════════════════════════════════════════════
r = call_tool("thought_summarize", {"chainId": cid1, "maxClusters": 3})
runner.test("thought_summarize", "correctness",
            lambda: ok(r) and "Theme" in text(r), "shows themed clusters")
runner.test("thought_summarize", "correctness",
            lambda: ok(r) and "thoughts" in text(r).lower(), "includes stats")

# ═══════════════════════════════════════════════════════════════
# 6. thought_to_plan (2 tests)
# ═══════════════════════════════════════════════════════════════
r = call_tool("thought_to_plan", {"chainId": cid1})
runner.test("thought_to_plan", "correctness",
            lambda: ok(r) and "Step" in text(r), "plan has actionable steps")

r = call_tool("thought_to_plan", {"chainId": cid1, "format": "json"})
runner.test("thought_to_plan", "edge-cases",
            lambda: ok(r) and '"step"' in text(r), "JSON format works")

# ═══════════════════════════════════════════════════════════════
# 7. thought_evaluate (2 tests)
# ═══════════════════════════════════════════════════════════════
r = call_tool("thought_evaluate", {"chainId": cid1, "thoughtNumber": 1})
runner.test("thought_evaluate", "correctness",
            lambda: ok(r) and ("Specificity" in text(r) or "specificity" in text(r).lower()),
            "shows quality dimensions")
runner.test("thought_evaluate", "correctness",
            lambda: ok(r) and "/10" in text(r), "includes numerical score")

# ═══════════════════════════════════════════════════════════════
# 8. thought_bridge (2 tests)
# ═══════════════════════════════════════════════════════════════
r = call_tool("thought_bridge", {"thought": "requirements analysis and testing"})
runner.test("thought_bridge", "correctness", lambda: ok(r), "bridge returns results")
runner.test("thought_bridge", "correctness",
            lambda: "Chain" in text(r) or "No cross" in text(r) or "connections" in text(r).lower(),
            "shows cross-chain connections")

# ═══════════════════════════════════════════════════════════════
# 9. assumptions (2 tests)
# ═══════════════════════════════════════════════════════════════
r = call_tool("assume", {"statement": "Server has 16GB RAM", "category": "environment"})
runner.test("assume", "correctness", lambda: ok(r), "assumption recorded")

r = call_tool("list_assumptions", {})
runner.test("list_assumptions", "correctness",
            lambda: ok(r) and ("16GB" in text(r) or "assumption" in text(r).lower()),
            "lists recorded assumptions")

# ═══════════════════════════════════════════════════════════════
# 10. model (3 tests)
# ═══════════════════════════════════════════════════════════════
test_dir = os.path.join(os.path.dirname(__file__))
r = call_tool("model_add", {"path": server, "role": "server"})
runner.test("model_add", "correctness", lambda: ok(r), "model file added")

r = call_tool("model_query", {"query": "What is the thinking server?"})
runner.test("model_query", "correctness",
            lambda: ok(r) and len(text(r)) > 0, "model query returns answer")

r = call_tool("model_stats", {})
runner.test("model_stats", "correctness", lambda: ok(r), "model stats returned")

# ═══════════════════════════════════════════════════════════════
# 11. Error handling (1 test)
# ═══════════════════════════════════════════════════════════════
r = call_tool("sequential_thinking", {"chainId": "nonexistent-chain-999"})
runner.test("error-handling", "error-handling",
            lambda: "not found" in str(r).lower() or "error" in json.dumps(r), "invalid chain rejected")

# ── Cleanup ──
proc.kill()
proc.wait()

print(runner.report())
