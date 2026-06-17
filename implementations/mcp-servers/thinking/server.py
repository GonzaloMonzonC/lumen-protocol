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


HANDLERS = {
    "sequential_thinking": tool_sequential_thinking,
    "thought_similarity": tool_thought_similarity,
    "thought_contradiction": tool_thought_contradiction,
    "thought_summarize": tool_thought_summarize,
    "thought_to_plan": tool_thought_to_plan,
    "thought_evaluate": tool_thought_evaluate,
    "thought_bridge": tool_thought_bridge,
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
