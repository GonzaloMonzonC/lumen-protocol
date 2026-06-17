#!/usr/bin/env python3
"""
LUMEN Sequential Thinking MCP Server — structured reasoning engine.

A reasoning notebook for LLMs. Instead of thinking inside the context window
(where thoughts get compressed and lost), the LLM writes thoughts to this
external tool that persists them, enables revision, branching, and analysis.

Enhanced with:
  - TF-IDF semantic similarity (zero deps, pure Python)
  - Contradiction detection
  - Automatic clustering by theme
  - Chain-to-plan conversion
  - Cross-chain bridging (knowledge reuse across sessions)

LUMEN benefits: 60-80% wire savings (highly structured data),
                 multi-agent shared reasoning, streaming for long chains.

Hermes config:
  mcp_servers:
    lumen_thinking:
      command: "python"
      args: ["server.py"]
      transport: lumen
"""

import sys
import json
import os
import re
import math
import time
from collections import defaultdict, Counter
from pathlib import Path
from typing import Any

# ═══════════════════════════════════════════════════════════════════════
# Data Model
# ═══════════════════════════════════════════════════════════════════════

_chains: dict[str, dict] = {}  # chain_id → chain

def _new_chain() -> str:
    """Create a new chain. Returns chain_id."""
    cid = f"chain_{len(_chains) + 1}_{int(time.time())}"
    _chains[cid] = {
        "thoughts": [],
        "created_at": time.time(),
        "updated_at": time.time(),
        "version": 1,
    }
    return cid


def _prune_old(n: int = 10) -> None:
    """Keep only the N most recent chains to avoid memory bloat."""
    if len(_chains) > n:
        oldest = sorted(_chains.keys(), key=lambda c: _chains[c]["updated_at"])
        for cid in oldest[:-n]:
            del _chains[cid]


# ═══════════════════════════════════════════════════════════════════════
# TF-IDF Engine (stdlib only — no numpy, scipy, or API deps)
# ═══════════════════════════════════════════════════════════════════════

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "shall", "this", "that",
    "it", "its", "i", "me", "my", "we", "our", "you", "your", "he", "she",
    "they", "them", "not", "no", "if", "so", "as", "just", "about", "into",
    "through", "during", "before", "after", "above", "below", "between",
})


def _tokenize(text: str) -> list[str]:
    """Tokenize: lowercase, split on non-alpha, remove stopwords & short tokens."""
    tokens = re.findall(r"[a-záéíóúñ]{3,}", text.lower())
    return [t for t in tokens if t not in _STOPWORDS]


def _build_tfidf(thoughts: list[dict]) -> tuple[list[dict[str, float]], dict[str, float]]:
    """
    Build TF-IDF vectors for a list of thoughts.
    Returns (vectors, idf) where each vector is {term: tfidf_score}.
    """
    if not thoughts:
        return [], {}

    # Tokenize all thoughts
    docs = [_tokenize(t["thought"]) for t in thoughts]
    N = len(docs)

    # Document frequency per term
    df: dict[str, int] = defaultdict(int)
    for doc in docs:
        for term in set(doc):
            df[term] += 1

    # IDF
    idf = {term: math.log((N + 1) / (freq + 1)) + 1.0 for term, freq in df.items()}

    # TF-IDF vectors
    vectors = []
    for doc in docs:
        tf = Counter(doc)
        vec = {}
        norm = 0.0
        for term, count in tf.items():
            if term in idf:
                score = count * idf[term]
                vec[term] = score
                norm += score * score
        # L2 normalize
        norm = math.sqrt(norm) if norm > 0 else 1.0
        vectors.append({t: s / norm for t, s in vec.items()})
    return vectors, idf


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two sparse TF-IDF vectors."""
    if not a or not b:
        return 0.0
    # Both are already L2-normalized, so dot product = cosine
    common = set(a) & set(b)
    return sum(a[t] * b[t] for t in common)


def _sentiment_heuristic(text: str) -> float:
    """Simple lexicon-free sentiment heuristic (-1 to +1)."""
    positive = {"mejor", "bueno", "excelente", "correcto", "funciona", "solución", "éxito",
                "eficiente", "óptimo", "recomiendo", "viable", "seguro", "robusto"}
    negative = {"error", "fallo", "falla", "incorrecto", "problema", "rompe", "riesgo",
                "lento", "peligroso", "fracaso", "inviable", "débil", "frágil", "no"}
    tokens = _tokenize(text)
    pos = sum(1 for t in tokens if t in positive)
    neg = sum(1 for t in tokens if t in negative)
    total = len(tokens) or 1
    return (pos - neg) / max(total, 1)


# ═══════════════════════════════════════════════════════════════════════
# Tool definitions
# ═══════════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "sequential_thinking",
        "description": "A structured thinking tool for dynamic and reflective problem-solving. Break down complex problems into manageable steps, revise earlier thoughts, branch into alternative reasoning paths, and verify hypotheses. Each thought is stored externally, surviving context compression.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "thought": {"type": "string", "description": "The current thinking step"},
                "nextThoughtNeeded": {"type": "boolean", "description": "Whether another thought step is needed after this one"},
                "thoughtNumber": {"type": "integer", "description": "Current thought number (1-based). Auto-generated if not provided.", "minimum": 1},
                "totalThoughts": {"type": "integer", "description": "Estimated total thoughts needed. Can be adjusted dynamically.", "minimum": 1},
                "isRevision": {"type": "boolean", "description": "Whether this revises a previous thought", "default": False},
                "revisesThought": {"type": "integer", "description": "Which thought number is being revised (required if isRevision=true)", "minimum": 1},
                "branchFromThought": {"type": "integer", "description": "Branch from this thought number to explore an alternative path", "minimum": 1},
                "branchId": {"type": "string", "description": "Identifier for this branch (e.g. 'alternative-plan')"},
                "needsMoreThoughts": {"type": "boolean", "description": "Set true to increase totalThoughts estimate", "default": False},
                "chainId": {"type": "string", "description": "ID of an existing chain to continue. Omit to create a new chain."}
            },
            "required": ["thought", "nextThoughtNeeded", "totalThoughts"]
        }
    },
    {
        "name": "thought_similarity",
        "description": "Find semantically similar thoughts in a chain using TF-IDF cosine similarity. Helps avoid repeating ideas and identifies related concepts across the reasoning chain. Zero external dependencies.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chainId": {"type": "string", "description": "Chain ID to search in"},
                "thought": {"type": "string", "description": "Thought to find similar matches for"},
                "topN": {"type": "integer", "description": "Number of similar thoughts to return (default: 3)", "default": 3, "maximum": 10},
                "minScore": {"type": "number", "description": "Minimum similarity score 0-1 (default: 0.1)", "default": 0.1}
            },
            "required": ["chainId", "thought"]
        }
    },
    {
        "name": "thought_contradiction",
        "description": "Detect thoughts in a chain that semantically contradict a given thought. Uses TF-IDF similarity with sentiment analysis to flag potential inconsistencies.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chainId": {"type": "string", "description": "Chain ID to check"},
                "thought": {"type": "string", "description": "Thought to check for contradictions against"}
            },
            "required": ["chainId", "thought"]
        }
    },
    {
        "name": "thought_summarize",
        "description": "Summarize a reasoning chain into a condensed overview. Groups thoughts by semantic cluster and provides a high-level summary of each cluster.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chainId": {"type": "string", "description": "Chain ID to summarize"},
                "maxClusters": {"type": "integer", "description": "Max number of theme clusters (default: 5)", "default": 5, "maximum": 10}
            },
            "required": ["chainId"]
        }
    },
    {
        "name": "thought_to_plan",
        "description": "Convert a reasoning chain into an actionable plan. Extracts concrete steps, identifies dependencies, and formats as a structured task list.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chainId": {"type": "string", "description": "Chain ID to convert into a plan"},
                "format": {"type": "string", "enum": ["markdown", "json"], "description": "Output format (default: markdown)", "default": "markdown"}
            },
            "required": ["chainId"]
        }
    },
    {
        "name": "thought_evaluate",
        "description": "Evaluate the quality of a thought within a chain. Scores consistency, specificity, and actionability. Provides constructive feedback for improvement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chainId": {"type": "string", "description": "Chain ID containing the thought"},
                "thoughtNumber": {"type": "integer", "description": "Thought number to evaluate", "minimum": 1}
            },
            "required": ["chainId", "thoughtNumber"]
        }
    },
    {
        "name": "thought_bridge",
        "description": "Find semantically related thoughts across DIFFERENT reasoning chains. Enables knowledge reuse: 'What did I think about this topic in a previous session?'",
        "inputSchema": {
            "type": "object",
            "properties": {
                "thought": {"type": "string", "description": "Thought to find cross-chain connections for"},
                "topN": {"type": "integer", "description": "Max cross-chain connections (default: 3)", "default": 3, "maximum": 5}
            }
        }
    },
    {
        "name": "assume",
        "description": "Explicitly record an assumption you are making. This EXPANDS your awareness of blind spots — it does NOT make decisions for you. The user can review and correct your assumptions. Use this when solving problems: 'I'm assuming X. Let me write that down so we can verify it later.'",
        "inputSchema": {
            "type": "object",
            "properties": {
                "statement": {"type": "string", "description": "The assumption you are making (e.g. 'the bug is in auth.py')"},
                "category": {"type": "string", "description": "Category: 'bug_location', 'user_env', 'dependency', 'performance', 'security', 'design', 'other'", "default": "other"},
                "confidence_note": {"type": "string", "description": "Why you think this might be true (e.g. 'based on error trace', 'user mentioned Windows')"}
            },
            "required": ["statement"]
        }
    },
    {
        "name": "list_assumptions",
        "description": "List all recorded assumptions. Shows which are confirmed, refuted, or unverified. Use this to review your blind spots before acting on them.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["all", "unverified", "confirmed", "refuted"], "description": "Filter by status (default: unverified)", "default": "unverified"},
                "category": {"type": "string", "description": "Filter by category"}
            }
        }
    },
    {
        "name": "check_assumption",
        "description": "Mark an assumption as confirmed or refuted after verification. Use this to close the loop: 'I assumed X — let me check... confirmed!' This builds a track record of your accuracy without automating decisions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "assumption_id": {"type": "integer", "description": "ID of the assumption to check"},
                "outcome": {"type": "string", "enum": ["confirmed", "refuted"], "description": "Was the assumption correct?"},
                "evidence": {"type": "string", "description": "What evidence confirmed or refuted it"}
            },
            "required": ["assumption_id", "outcome"]
        }
    },
    {
        "name": "model_add",
        "description": "Add a file or directory to the project mental model. Build a living map of the project so the agent understands its structure without re-reading everything. This is purely FACTUAL — no opinions or automation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory path (relative to project root)"},
                "role": {"type": "string", "description": "What this file does: 'authentication', 'database', 'config', 'api', 'model', 'test', 'util', 'entry_point', 'other'"},
                "deps": {"type": "array", "items": {"type": "string"}, "description": "List of files this depends on"},
                "notes": {"type": "string", "description": "Brief note about this file (e.g. 'Handles JWT token validation')"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "model_query",
        "description": "Query the project mental model. Ask: 'what files depend on X?', 'what role does Y have?', 'what would break if I change Z?'",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to ask: 'deps of <path>', 'dependents of <path>', 'role=<role>', 'impact of <path>', 'all'"},
                "target": {"type": "string", "description": "File path or role name to query about"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "model_stats",
        "description": "Get statistics about the project mental model: how many files are mapped, what roles exist, dependency density.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "model_map",
        "description": "Generate a visual tree map of the project from the mental model. Shows files, their roles, and dependency relationships.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root_path": {"type": "string", "description": "Root directory to start the map from (default: project root)", "default": "."},
                "max_depth": {"type": "integer", "description": "Max depth to show (default: 3)", "default": 3, "maximum": 5}
            }
        }
    },
    {
        "name": "model_remove",
        "description": "Remove a file from the mental model when it's deleted or no longer relevant. Automatically updates all dependency links.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to remove from the model"}
            },
            "required": ["path"]
        }
    }
]


# ═══════════════════════════════════════════════════════════════════════
# Tool implementations
# ═══════════════════════════════════════════════════════════════════════

def tool_sequential_thinking(args: dict) -> dict:
    """Core: record a thought in a reasoning chain."""
    thought_text = args["thought"]
    next_needed = args["nextThoughtNeeded"]
    total_thoughts = args["totalThoughts"]
    thought_number = args.get("thoughtNumber")
    is_revision = args.get("isRevision", False)
    revises = args.get("revisesThought")
    branch_from = args.get("branchFromThought")
    branch_id = args.get("branchId")
    needs_more = args.get("needsMoreThoughts", False)
    chain_id = args.get("chainId")

    # Get or create chain
    if chain_id and chain_id in _chains:
        chain = _chains[chain_id]
    else:
        chain_id = _new_chain()
        chain = _chains[chain_id]

    # Auto-number if not provided
    if thought_number is None:
        thought_number = len(chain["thoughts"]) + 1
    elif needs_more:
        total_thoughts = max(total_thoughts, thought_number + 1)

    thought_obj = {
        "number": thought_number,
        "thought": thought_text,
        "totalThoughts": total_thoughts,
        "nextThoughtNeeded": next_needed,
        "isRevision": is_revision,
        "revisesThought": revises,
        "branchFromThought": branch_from,
        "branchId": branch_id,
        "timestamp": time.time(),
    }

    # If revision, mark original
    if is_revision and revises:
        for t in chain["thoughts"]:
            if t["number"] == revises:
                t["revisedBy"] = thought_number
                break

    chain["thoughts"].append(thought_obj)
    chain["updated_at"] = time.time()
    chain["version"] += 1
    _prune_old()

    # Build response with context
    summary_lines = [
        f"✅ Thought #{thought_number} recorded in chain '{chain_id}'",
        f"   Total thoughts: {len(chain['thoughts'])} / {total_thoughts}",
    ]
    if is_revision:
        summary_lines.append(f"   🔄 Revision of thought #{revises}")
    if branch_from:
        summary_lines.append(f"   🌿 Branch from thought #{branch_from}" + (f" ({branch_id})" if branch_id else ""))
    if next_needed:
        summary_lines.append(f"   ➡️  Next thought expected (totalThoughts={total_thoughts})")
    else:
        summary_lines.append(f"   🏁 Chain complete ({len(chain['thoughts'])} thoughts)")

    # Show recent thoughts for context
    summary_lines.append(f"\n   Recent thoughts:")
    for t in chain["thoughts"][-5:]:
        marker = "🔄" if t.get("isRevision") else "🌿" if t.get("branchFromThought") else "  "
        summary_lines.append(f"   {marker} #{t['number']}: {t['thought'][:80]}...")

    return {
        "content": [{"type": "text", "text": "\n".join(summary_lines)}],
        "chainId": chain_id,
        "thoughtCount": len(chain["thoughts"]),
    }


def tool_thought_similarity(args: dict) -> dict:
    """Find similar thoughts in a chain."""
    chain_id = args["chainId"]
    thought_text = args["thought"]
    top_n = min(args.get("topN", 3), 10)
    min_score = args.get("minScore", 0.1)

    if chain_id not in _chains:
        return {"content": [{"type": "text", "text": f"Error: Chain '{chain_id}' not found"}]}

    chain = _chains[chain_id]
    thoughts = chain["thoughts"]
    if len(thoughts) < 2:
        return {"content": [{"type": "text", "text": "Not enough thoughts for similarity analysis (need ≥2)"}]}

    vectors, idf = _build_tfidf(thoughts)
    # Build vector for the query thought
    query_tokens = _tokenize(thought_text)
    query_vec = {}
    if query_tokens:
        tf = Counter(query_tokens)
        norm = 0.0
        for term, count in tf.items():
            if term in idf:
                score = count * idf[term]
                query_vec[term] = score
                norm += score * score
        norm = math.sqrt(norm) if norm > 0 else 1.0
        query_vec = {t: s / norm for t, s in query_vec.items()}

    scores = []
    for i, vec in enumerate(vectors):
        sim = _cosine_similarity(query_vec, vec)
        if sim >= min_score:
            t = thoughts[i]
            scores.append((sim, t["number"], t["thought"][:120]))

    scores.sort(reverse=True)
    top = scores[:top_n]

    if not top:
        return {"content": [{"type": "text", "text": "No similar thoughts found above minimum score."}]}

    lines = [f"🔍 Top {len(top)} similar thoughts in chain '{chain_id}':"]
    for sim, num, text in top:
        bar = "█" * int(sim * 10) + "░" * (10 - int(sim * 10))
        lines.append(f"   {bar} {sim:.0%} — #{num}: {text}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_thought_contradiction(args: dict) -> dict:
    """Detect contradictory thoughts."""
    chain_id = args["chainId"]
    thought_text = args["thought"]

    if chain_id not in _chains:
        return {"content": [{"type": "text", "text": f"Error: Chain '{chain_id}' not found"}]}

    chain = _chains[chain_id]
    thoughts = chain["thoughts"]
    if not thoughts:
        return {"content": [{"type": "text", "text": "No thoughts in chain to check against."}]}

    query_sentiment = _sentiment_heuristic(thought_text)
    vectors, idf = _build_tfidf(thoughts)

    # Build query vector
    query_tokens = _tokenize(thought_text)
    query_vec = {}
    if query_tokens:
        tf = Counter(query_tokens)
        norm = 0.0
        for term, count in tf.items():
            if term in idf:
                score = count * idf[term]
                query_vec[term] = score
                norm += score * score
        norm = math.sqrt(norm) if norm > 0 else 1.0
        query_vec = {t: s / norm for t, s in query_vec.items()}

    contradictions = []
    for i, (vec, t) in enumerate(zip(vectors, thoughts)):
        sim = _cosine_similarity(query_vec, vec)
        t_sentiment = _sentiment_heuristic(t["thought"])

        # Contradiction: similar topic (sim > 0.15) BUT opposite sentiment
        if sim > 0.15 and abs(query_sentiment - t_sentiment) > 0.3:
            sign_q = "positive" if query_sentiment > 0 else "negative"
            sign_t = "positive" if t_sentiment > 0 else "negative"
            contradictions.append({
                "number": t["number"],
                "thought": t["thought"][:150],
                "similarity": round(sim, 2),
                "issue": f"Similar topic but opposite tone ({sign_q} vs {sign_t})"
            })

    if not contradictions:
        return {"content": [{"type": "text", "text": "✅ No contradictions detected in the chain."}]}

    lines = [f"⚠️  Found {len(contradictions)} potential contradiction(s):"]
    for c in contradictions:
        lines.append(f"   #{c['number']}: {c['issue']}")
        lines.append(f"      \"{c['thought'][:100]}...\"")
        lines.append(f"      (similarity: {c['similarity']:.0%})")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_thought_summarize(args: dict) -> dict:
    """Summarize a chain via semantic clustering."""
    chain_id = args["chainId"]
    max_clusters = min(args.get("maxClusters", 5), 10)

    if chain_id not in _chains:
        return {"content": [{"type": "text", "text": f"Error: Chain '{chain_id}' not found"}]}

    chain = _chains[chain_id]
    thoughts = chain["thoughts"]
    if not thoughts:
        return {"content": [{"type": "text", "text": "Chain is empty. Nothing to summarize."}]}

    if len(thoughts) == 1:
        return {"content": [{"type": "text", "text": f"Chain has 1 thought: \"{thoughts[0]['thought'][:200]}\""}]}

    vectors, idf = _build_tfidf(thoughts)

    # Simple agglomerative clustering based on cosine similarity
    n = len(vectors)
    clusters = [[i] for i in range(n)]  # each thought starts alone

    while len(clusters) > max_clusters:
        # Find most similar pair of clusters
        best_sim = -1
        best_pair = (0, 1)
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                # Average linkage similarity
                sims = []
                for ai in clusters[i]:
                    for bj in clusters[j]:
                        sims.append(_cosine_similarity(vectors[ai], vectors[bj]))
                avg_sim = sum(sims) / len(sims) if sims else 0
                if avg_sim > best_sim:
                    best_sim = avg_sim
                    best_pair = (i, j)

        if best_sim < 0.05:
            break

        # Merge
        i, j = best_pair
        clusters[i].extend(clusters[j])
        clusters.pop(j)

    # Generate cluster labels from top TF-IDF terms
    lines = [f"📋 Summary of chain '{chain_id}' — {len(thoughts)} thoughts in {len(clusters)} theme(s):"]
    for ci, cluster in enumerate(clusters, 1):
        # Find top terms for this cluster
        all_terms = Counter()
        for idx in cluster:
            for term, score in vectors[idx].items():
                all_terms[term] += score
        top_terms = [t for t, _ in all_terms.most_common(5)]

        thoughts_in_cluster = [thoughts[i] for i in cluster]
        lines.append(f"\n   🏷️  Theme {ci}: {', '.join(top_terms[:3])}")
        lines.append(f"      {len(thoughts_in_cluster)} thoughts (#{thoughts_in_cluster[0]['number']}–#{thoughts_in_cluster[-1]['number']})")
        for t in thoughts_in_cluster[:3]:
            lines.append(f"         #{t['number']}: {t['thought'][:100]}...")
        if len(thoughts_in_cluster) > 3:
            lines.append(f"         ... and {len(thoughts_in_cluster) - 3} more")

    # Overall stats
    revisions = sum(1 for t in thoughts if t.get("isRevision"))
    branches = sum(1 for t in thoughts if t.get("branchFromThought"))
    lines.append(f"\n   📊 {len(thoughts)} thoughts | {revisions} revisions | {branches} branches | {len(clusters)} themes")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_thought_to_plan(args: dict) -> dict:
    """Convert chain to actionable plan."""
    chain_id = args["chainId"]
    fmt = args.get("format", "markdown")

    if chain_id not in _chains:
        return {"content": [{"type": "text", "text": f"Error: Chain '{chain_id}' not found"}]}

    chain = _chains[chain_id]
    thoughts = chain["thoughts"]

    # Filter out revisions, keep only final thoughts
    revised = {t["revisesThought"] for t in thoughts if t.get("revisesThought")}
    active = [t for t in thoughts if t["number"] not in revised and not t.get("isRevision")]

    if not active:
        return {"content": [{"type": "text", "text": "No actionable thoughts after filtering revisions."}]}

    if fmt == "json":
        plan = {
            "chainId": chain_id,
            "totalSteps": len(active),
            "steps": [{"step": i + 1, "number": t["number"], "action": t["thought"]} for i, t in enumerate(active)]
        }
        return {"content": [{"type": "text", "text": json.dumps(plan, indent=2, ensure_ascii=False)}]}

    # Markdown plan
    lines = [f"# 📋 Action Plan — Chain '{chain_id}'", ""]
    lines.append(f"**{len(active)} steps** extracted from {len(thoughts)} thoughts")
    lines.append("")

    for i, t in enumerate(active, 1):
        lines.append(f"## Step {i}")
        lines.append(f"**Origin**: Thought #{t['number']}")
        lines.append(f"**Action**: {t['thought']}")
        if i < len(active):
            lines.append(f"**Depends on**: Step {i + 1}")
        lines.append("")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_thought_evaluate(args: dict) -> dict:
    """Evaluate thought quality."""
    chain_id = args["chainId"]
    thought_number = args["thoughtNumber"]

    if chain_id not in _chains:
        return {"content": [{"type": "text", "text": f"Error: Chain '{chain_id}' not found"}]}

    chain = _chains[chain_id]
    target = None
    for t in chain["thoughts"]:
        if t["number"] == thought_number:
            target = t
            break

    if not target:
        return {"content": [{"type": "text", "text": f"Error: Thought #{thought_number} not found in chain '{chain_id}'"}]}

    thought_text = target["thought"]

    # Heuristic evaluation
    specificity = min(len(thought_text) / 200, 1.0)  # longer = more specific
    has_numbers = bool(re.search(r'\d+', thought_text))
    has_action = any(w in thought_text.lower() for w in
                     ["hacer", "crear", "ejecutar", "analizar", "implementar",
                      "migrar", "configurar", "build", "deploy", "run", "test",
                      "create", "execute", "analyze"])

    scores = {
        "specificity": round(specificity * 10, 1),
        "actionability": 10.0 if has_action else 3.0,
        "concreteness": 10.0 if has_numbers else 5.0,
    }
    overall = round(sum(scores.values()) / len(scores), 1)

    feedback = []
    if specificity < 0.3:
        feedback.append("💡 Be more specific — add details, numbers, or concrete steps")
    if not has_action:
        feedback.append("💡 Add an action verb to make this thought actionable")
    if not has_numbers:
        feedback.append("💡 Include numbers (time estimates, counts, versions)")
    if overall >= 8:
        feedback.append("✅ Excellent thought — specific, actionable, and concrete")

    lines = [
        f"📊 Evaluation of Thought #{thought_number} in chain '{chain_id}'",
        f"   Overall: {'⭐' * int(overall / 2)} {overall}/10",
        f"   Specificity:   {scores['specificity']}/10",
        f"   Actionability: {scores['actionability']}/10",
        f"   Concreteness:  {scores['concreteness']}/10",
        "",
    ] + feedback

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_thought_bridge(args: dict) -> dict:
    """Cross-chain thought connections."""
    thought_text = args["thought"]
    top_n = min(args.get("topN", 3), 5)

    if len(_chains) < 2:
        return {"content": [{"type": "text", "text": "Need at least 2 chains for cross-chain bridging."}]}

    # Build query vector
    query_tokens = _tokenize(thought_text)
    if not query_tokens:
        return {"content": [{"type": "text", "text": "No meaningful tokens in thought to bridge."}]}

    connections = []
    for cid, chain in _chains.items():
        thoughts = chain["thoughts"]
        if not thoughts:
            continue

        vectors, idf = _build_tfidf(thoughts)
        query_vec = {}
        norm = 0.0
        tf = Counter(query_tokens)
        for term, count in tf.items():
            if term in idf:
                score = count * idf[term]
                query_vec[term] = score
                norm += score * score
        norm = math.sqrt(norm) if norm > 0 else 1.0
        query_vec = {t: s / norm for t, s in query_vec.items()}

        best_sim = 0
        best_thought = None
        for i, vec in enumerate(vectors):
            sim = _cosine_similarity(query_vec, vec)
            if sim > best_sim:
                best_sim = sim
                best_thought = thoughts[i]

        if best_sim > 0.1 and best_thought:
            connections.append((cid, best_sim, best_thought))

    connections.sort(key=lambda x: x[1], reverse=True)
    top = connections[:top_n]

    if not top:
        return {"content": [{"type": "text", "text": "No cross-chain connections found. Try a more specific thought."}]}

    lines = [f"🌉 Cross-chain bridges for: \"{thought_text[:80]}...\""]
    for cid, sim, t in top:
        bar = "█" * int(sim * 10) + "░" * (10 - int(sim * 10))
        lines.append(f"   {bar} {sim:.0%} — Chain '{cid}', #{t['number']}: {t['thought'][:100]}...")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


# ═══════════════════════════════════════════════════════════════════════
# Assumption Tracker — cognitive safety tools
# ═══════════════════════════════════════════════════════════════════════

_assumptions: list[dict] = []
_next_assumption_id = 1


def tool_assume(args: dict) -> dict:
    """Record an assumption explicitly."""
    global _next_assumption_id

    statement = args["statement"]
    category = args.get("category", "other")
    confidence_note = args.get("confidence_note", "")

    assumption = {
        "id": _next_assumption_id,
        "statement": statement,
        "category": category,
        "confidence_note": confidence_note,
        "status": "unverified",
        "timestamp": time.time(),
    }
    _assumptions.append(assumption)
    _next_assumption_id += 1

    lines = [
        f"📝 Assumption #{assumption['id']} recorded:",
        f"   \"{statement}\"",
        f"   Category: {category}",
    ]
    if confidence_note:
        lines.append(f"   Basis: {confidence_note}")
    lines.append(f"   Status: ⏳ unverified — check later with check_assumption")

    # Show related unverified assumptions for awareness
    unverified = [a for a in _assumptions if a["status"] == "unverified" and a["id"] != assumption["id"]]
    if unverified:
        lines.append(f"\n   ⚠️  You have {len(unverified)} other unverified assumption(s):")
        for a in unverified[-3:]:
            lines.append(f"      #{a['id']}: {a['statement'][:80]}...")
        if len(unverified) > 3:
            lines.append(f"      ... and {len(unverified)-3} more. Use list_assumptions() to see all.")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_list_assumptions(args: dict) -> dict:
    """List assumptions with optional filtering."""
    status_filter = args.get("status", "unverified")
    category_filter = args.get("category")

    filtered = _assumptions
    if status_filter != "all":
        filtered = [a for a in filtered if a["status"] == status_filter]
    if category_filter:
        filtered = [a for a in filtered if a["category"] == category_filter]

    if not filtered:
        return {"content": [{"type": "text", "text": f"No assumptions found (filter: status={status_filter}, category={category_filter or 'any'})."}]}

    total = len(_assumptions)
    confirmed = sum(1 for a in _assumptions if a["status"] == "confirmed")
    refuted = sum(1 for a in _assumptions if a["status"] == "refuted")
    unverified_count = total - confirmed - refuted

    lines = [f"📋 Assumptions ({len(filtered)} shown, {total} total)"]
    lines.append(f"   ✅ {confirmed} confirmed | ❌ {refuted} refuted | ⏳ {unverified_count} unverified")
    lines.append("")

    for a in filtered:
        icon = {"unverified": "⏳", "confirmed": "✅", "refuted": "❌"}.get(a["status"], "?")
        lines.append(f"   {icon} #{a['id']} [{a['category']}] {a['statement'][:120]}")
        if a.get("evidence"):
            lines.append(f"      Evidence: {a['evidence'][:100]}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_check_assumption(args: dict) -> dict:
    """Mark an assumption as confirmed or refuted."""
    aid = args["assumption_id"]
    outcome = args["outcome"]
    evidence = args.get("evidence", "")

    target = None
    for a in _assumptions:
        if a["id"] == aid:
            target = a
            break

    if not target:
        return {"content": [{"type": "text", "text": f"Error: Assumption #{aid} not found."}]}

    target["status"] = outcome
    target["evidence"] = evidence
    target["checked_at"] = time.time()

    icon = "✅" if outcome == "confirmed" else "❌"
    lines = [f"{icon} Assumption #{aid} → {outcome}"]
    lines.append(f"   \"{target['statement'][:120]}\"")
    if evidence:
        lines.append(f"   Evidence: {evidence[:200]}")

    # Show learning: how many right/wrong so far
    confirmed = sum(1 for a in _assumptions if a["status"] == "confirmed")
    refuted = sum(1 for a in _assumptions if a["status"] == "refuted")
    total_checked = confirmed + refuted
    if total_checked > 0:
        pct = confirmed * 100 // total_checked
        lines.append(f"\n   📊 Track record: {confirmed}/{total_checked} confirmed ({pct}%)")
        if pct < 50:
            lines.append(f"   💡 Your assumptions are often wrong — consider listing them before acting.")
        elif pct > 80:
            lines.append(f"   💡 Your assumptions are usually right — but don't get overconfident.")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


# ═══════════════════════════════════════════════════════════════════════
# Mental Model Builder — project knowledge graph
# ═══════════════════════════════════════════════════════════════════════

_model: dict[str, dict] = {}  # path → {role, deps, dependents, notes, added_at}


def _update_dependents():
    """Recalculate reverse dependencies (who depends on whom)."""
    for path in _model:
        _model[path]["dependents"] = []
    for path, node in _model.items():
        for dep in node.get("deps", []):
            if dep in _model:
                _model[dep]["dependents"].append(path)


def tool_model_add(args: dict) -> dict:
    """Add a file to the mental model."""
    path = args["path"]
    role = args.get("role", "other")
    deps = args.get("deps", [])
    notes = args.get("notes", "")

    existing = path in _model

    _model[path] = {
        "role": role,
        "deps": list(deps),
        "dependents": [],
        "notes": notes,
        "added_at": time.time(),
    }
    _update_dependents()

    action = "Updated" if existing else "Added"
    lines = [f"🧠 {action} to model: {path}"]
    if role != "other":
        lines.append(f"   Role: {role}")
    if deps:
        lines.append(f"   Dependencies: {', '.join(deps[:5])}")
    if notes:
        lines.append(f"   Notes: {notes[:120]}")

    # Show connected files
    connected = set(deps)
    for p, node in _model.items():
        if path in node.get("deps", []) and p != path:
            connected.add(p)
    if connected:
        lines.append(f"   🔗 Connected: {len(connected)} file(s)")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_model_query(args: dict) -> dict:
    """Query the mental model."""
    query = args["query"].strip()
    target = args.get("target", "")

    if not _model:
        return {"content": [{"type": "text", "text": "Model is empty. Use model_add to populate it first."}]}

    lines = []

    # "deps of path"
    if query.startswith("deps of ") or query.startswith("deps "):
        path = target or query.replace("deps of ", "").replace("deps ", "").strip()
        if path in _model:
            deps = _model[path].get("deps", [])
            lines.append(f"📦 Dependencies of {path} ({_model[path].get('role','?')}):")
            for d in deps:
                role_str = f" [{_model[d]['role']}]" if d in _model else " [unknown]"
                lines.append(f"   → {d}{role_str}")
            if not deps:
                lines.append("   (no dependencies)")
        else:
            lines.append(f"❌ '{path}' not in model. Add it with model_add first.")

    # "dependents of path" / "who depends on path"
    elif "dependent" in query or "who depends" in query:
        path = target or query.split("of ")[-1].strip()
        if path in _model:
            deps_of = _model[path].get("dependents", [])
            lines.append(f"📦 Files that depend on {path}:")
            for d in deps_of:
                lines.append(f"   ← {d} [{_model[d].get('role','?')}]")
            if not deps_of:
                lines.append(f"   ✅ No files depend on {path} — safe to change!")
        else:
            lines.append(f"❌ '{path}' not in model.")

    # "role=X"
    elif query.startswith("role="):
        role = query.replace("role=", "").strip()
        matches = [p for p, n in _model.items() if n.get("role") == role]
        lines.append(f"📦 Files with role '{role}' ({len(matches)}):")
        for m in sorted(matches):
            lines.append(f"   {m}" + (f" — {_model[m].get('notes','')[:60]}" if _model[m].get('notes') else ""))

    # "impact of path"
    elif "impact" in query:
        path = target or query.split("of ")[-1].strip()
        if path in _model:
            deps_of = _model[path].get("dependents", [])
            lines.append(f"💥 Impact of changing {path}:")
            if deps_of:
                lines.append(f"   {len(deps_of)} file(s) would be affected:")
                for d in deps_of:
                    lines.append(f"   ⚠️  {d} [{_model[d].get('role','?')}]")
            else:
                lines.append(f"   ✅ No impact — safe to change!")
        else:
            lines.append(f"❌ '{path}' not in model.")

    # "all"
    elif query == "all":
        lines.append(f"📦 Full model ({len(_model)} files):")
        for path in sorted(_model):
            n = _model[path]
            lines.append(f"   {path} [{n.get('role','?')}] → {len(n.get('deps',[]))} deps, {len(n.get('dependents',[]))} users")

    else:
        lines.append(f"❓ Unknown query: '{query}'")
        lines.append("Try: 'deps of <path>', 'dependents of <path>', 'role=<name>', 'impact of <path>', 'all'")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_model_stats(args: dict) -> dict:
    """Model statistics."""
    if not _model:
        return {"content": [{"type": "text", "text": "Model is empty."}]}

    roles = Counter(n.get("role", "other") for n in _model.values())
    total_deps = sum(len(n.get("deps", [])) for n in _model.values())
    total_files = len(_model)
    avg_deps = total_deps / total_files if total_files else 0

    # Most connected files
    connections = [(p, len(n.get("deps", [])) + len(n.get("dependents", []))) for p, n in _model.items()]
    connections.sort(key=lambda x: -x[1])

    lines = [
        f"📊 Mental Model Stats:",
        f"   Files mapped:   {total_files}",
        f"   Dependencies:   {total_deps} (avg {avg_deps:.1f}/file)",
        f"",
        f"   Roles:",
    ]
    for role, count in roles.most_common():
        bar = "█" * min(count, 30)
        lines.append(f"   {role:<20} {bar} {count}")

    lines.append(f"\n   Most connected files:")
    for path, conn in connections[:5]:
        n = _model[path]
        lines.append(f"   {path} [{n.get('role','?')}] — {conn} connections")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_model_map(args: dict) -> dict:
    """Visual tree map of the model."""
    if not _model:
        return {"content": [{"type": "text", "text": "Model is empty."}]}

    root = args.get("root_path", ".")
    max_depth = args.get("max_depth", 3)

    # Build tree from paths
    lines = [f"🗺️  Project Map:"]

    # Find entry points (files with no incoming deps from the model)
    has_dependents = set()
    for n in _model.values():
        for d in n.get("dependents", []):
            has_dependents.add(d)

    # Entry points: files with dependents but no deps within model, OR files with deps but no dependents
    entries = sorted(_model.keys())

    # Group by directory
    dirs: dict[str, list] = {}
    for path in entries:
        d = os.path.dirname(path) or "."
        if d not in dirs:
            dirs[d] = []
        dirs[d].append(path)

    for directory in sorted(dirs):
        lines.append(f"\n📁 {directory}/")
        for path in sorted(dirs[directory]):
            n = _model[path]
            fname = os.path.basename(path)
            role_icon = {"authentication":"🔐","database":"🗄️","config":"⚙️","api":"🔌","model":"📊","test":"🧪","util":"🔧","entry_point":"🚀"}.get(n.get("role",""),"📄")
            deps_str = f" → {', '.join(n.get('deps',[])[:3])}" if n.get("deps") else ""
            lines.append(f"   {role_icon} {fname} [{n.get('role','?')}]{deps_str}")

    lines.append(f"\n📊 {len(_model)} files mapped across {len(dirs)} directories")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_model_remove(args: dict) -> dict:
    """Remove a file from the mental model."""
    path = args["path"]

    if path not in _model:
        return {"content": [{"type": "text", "text": f"'{path}' is not in the model."}]}

    # Find what depends on this file
    affected = _model[path].get("dependents", [])
    role = _model[path].get("role", "?")

    del _model[path]
    _update_dependents()

    lines = [f"🗑️  Removed from model: {path} [{role}]"]
    if affected:
        lines.append(f"   ⚠️  {len(affected)} file(s) had this as dependency:")
        for a in affected:
            lines.append(f"      {a} — check if still valid")
    lines.append(f"   Model now has {len(_model)} file(s)")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


HANDLERS = {
    "sequential_thinking": tool_sequential_thinking,
    "thought_similarity": tool_thought_similarity,
    "thought_contradiction": tool_thought_contradiction,
    "thought_summarize": tool_thought_summarize,
    "thought_to_plan": tool_thought_to_plan,
    "thought_evaluate": tool_thought_evaluate,
    "thought_bridge": tool_thought_bridge,
    "assume": tool_assume,
    "list_assumptions": tool_list_assumptions,
    "check_assumption": tool_check_assumption,
    "model_add": tool_model_add,
    "model_query": tool_model_query,
    "model_stats": tool_model_stats,
    "model_map": tool_model_map,
    "model_remove": tool_model_remove,
}


# ═══════════════════════════════════════════════════════════════════════
# MCP Server (JSON-RPC over stdio)
# ═══════════════════════════════════════════════════════════════════════

def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle_message(msg: dict) -> None:
    method = msg.get("method", "")
    req_id = msg.get("id")

    if method == "initialize":
        send({
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lumen-thinking", "version": "2.0.0"}
            }
        })
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        handler = HANDLERS.get(tool_name)
        if handler:
            try:
                result = handler(tool_args)
                send({"jsonrpc": "2.0", "id": req_id, "result": result})
            except Exception as e:
                send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": f"Tool error: {e}"}})
        else:
            send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}})
    elif method == "notifications/initialized":
        pass
    else:
        send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}})


def main() -> None:
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            handle_message(msg)
        except json.JSONDecodeError:
            pass


if __name__ == "__main__":
    main()
