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

from __future__ import annotations

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
# Data Model — Multi-agent session isolation
# ═══════════════════════════════════════════════════════════════════════

class Session:
    """Per-agent isolated state: chains, assumptions, model, work log."""
    def __init__(self, label: str = ""):
        self.label = label
        self.chains: dict[str, dict] = {}
        self.assumptions: list[dict] = []
        self.next_assumption_id = 1
        self.model: dict[str, dict] = {}
        self.works: list[dict] = []
        self.next_work_id = 1
        self.tool_calls = 0
        self.created_at = time.time()
        self.updated_at = time.time()

_sessions: dict[str, Session] = {}  # session_id → Session
_DEFAULT_SESSION = "default"
_next_session_num = 1

def _get_session(session_id: str | None = None) -> Session:
    """Get or create a session. None → default session."""
    sid = session_id or _DEFAULT_SESSION
    if sid not in _sessions:
        _sessions[sid] = Session(label=sid)
    _sessions[sid].updated_at = time.time()
    _sessions[sid].tool_calls += 1
    return _sessions[sid]

def _new_chain(session: Session) -> str:
    """Create a new chain in a session. Returns chain_id."""
    cid = f"chain_{len(session.chains) + 1}_{int(time.time())}"
    session.chains[cid] = {
        "thoughts": [],
        "created_at": time.time(),
        "updated_at": time.time(),
        "version": 1,
    }
    return cid

def _prune_old(session: Session, n: int = 10) -> None:
    """Keep only the N most recent chains in a session."""
    if len(session.chains) > n:
        oldest = sorted(session.chains.keys(), key=lambda c: session.chains[c]["updated_at"])
        for cid in oldest[:-n]:
            del session.chains[cid]

# Legacy compatibility: alias globals to default session properties
def _chains() -> dict: return _get_session().chains
def _assumptions() -> list: return _get_session().assumptions
def _model() -> dict: return _get_session().model
def _works() -> list: return _get_session().works


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
    },
    {
        "name": "context_preserve",
        "description": "Mark a piece of information as critical to preserve. Use when you discover something important that MUST survive context compression: a key finding, a user preference, a decision rationale, a bug root cause. This is your 'don't forget this' tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The information to preserve"},
                "priority": {"type": "string", "enum": ["critical", "high", "medium"], "description": "How critical is this? (default: high)", "default": "high"},
                "category": {"type": "string", "description": "Category: 'finding', 'decision', 'user_pref', 'bug_cause', 'architecture', 'todo', 'other'", "default": "other"}
            },
            "required": ["content"]
        }
    },
    {
        "name": "context_check",
        "description": "Check what information has been preserved and assess decay risk. Shows the preservation list with priorities, suggests what might be at risk of being lost. Use this when the conversation gets long or before a context compression event.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_items": {"type": "integer", "description": "Max items to show (default: 20)", "default": 20}
            }
        }
    },
    {
        "name": "work_start",
        "description": "Start tracking a work item. Use when beginning a task: 'I'm starting X'. Survives across sessions (persists in local JSON file) — unlike Hermes built-in todo which is per-session. This is purely FACTUAL: what you're doing, not how to do it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item": {"type": "string", "description": "What you're working on (e.g. 'fix auth bug #42')"},
                "category": {"type": "string", "description": "Category: 'bug', 'feature', 'refactor', 'docs', 'review', 'other'", "default": "other"}
            },
            "required": ["item"]
        }
    },
    {
        "name": "work_block",
        "description": "Mark a work item as blocked. Use when you can't continue because you're waiting for something: PR review, user feedback, dependency. The agent can later check what's blocked and follow up.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "work_id": {"type": "integer", "description": "ID of the work item to mark as blocked"},
                "reason": {"type": "string", "description": "Why it's blocked (e.g. 'waiting for PR review from Nous')"}
            },
            "required": ["work_id", "reason"]
        }
    },
    {
        "name": "work_done",
        "description": "Mark a work item as completed. Use when you finish something: 'Done with X'. Records completion for future reference. The agent can see what was accomplished in past sessions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "work_id": {"type": "integer", "description": "ID of the work item to mark as done"},
                "result": {"type": "string", "description": "What was the outcome? (e.g. 'PR merged', 'bug fixed in commit abc123')"}
            },
            "required": ["work_id"]
        }
    },
    {
        "name": "work_log",
        "description": "Show the work log: what's in progress, blocked, done. Filterable by status. Survives across sessions — gives the agent continuity when resuming work.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["all", "in_progress", "blocked", "done"], "description": "Filter by status (default: all)", "default": "all"},
                "limit": {"type": "integer", "description": "Max items to show (default: 20)", "default": 20}
            }
        }
    },
    {
        "name": "context_estimate",
        "description": "Estimate how much context is being used and suggest what to externalize. Based on session activity: tool call count, response sizes, task complexity. Does NOT measure actual tokens — this is a heuristic. Helps the agent be proactive about offloading before context compression hits.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "session_init",
        "description": "Create or retrieve a multi-agent session. Sessions isolate chains, assumptions, models, and work logs so multiple agents can share a transport without state collisions. Returns a session_id for use in other tool calls.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "Human-friendly session label (e.g. 'agent-a', 'code-review')"},
                "session_id": {"type": "string", "description": "Existing session ID to resume. Creates a new one if omitted."}
            }
        }
    },
    {
        "name": "session_list",
        "description": "List all active sessions with their stats (chains, assumptions, model size, tool calls).",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]


# ═══════════════════════════════════════════════════════════════════════
# Tool implementations
# ═══════════════════════════════════════════════════════════════════════

def tool_sequential_thinking(args: dict) -> dict:
    """Core: record a thought in a reasoning chain."""
    session = _get_session(args.get("session_id"))
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

    # Auto-create chain if needed
    if not chain_id:
        chain_id = _new_chain(session)
    elif chain_id not in session.chains:
        return {"content": [{"type": "text", "text": f"Chain '{chain_id}' not found in session. Start a new chain or check the session_id."}]}

    chain = session.chains[chain_id]

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
    _prune_old(session)

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
    session = _get_session(args.get("session_id"))  # multi-agent
    chain_id = args["chainId"]
    thought_text = args["thought"]
    top_n = min(args.get("topN", 3), 10)
    min_score = args.get("minScore", 0.1)

    if chain_id not in session.chains:
        return {"content": [{"type": "text", "text": f"Error: Chain '{chain_id}' not found"}]}

    chain = session.chains[chain_id]
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
    session = _get_session(args.get("session_id"))  # multi-agent
    chain_id = args["chainId"]
    thought_text = args["thought"]

    if chain_id not in session.chains:
        return {"content": [{"type": "text", "text": f"Error: Chain '{chain_id}' not found"}]}

    chain = session.chains[chain_id]
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
    session = _get_session(args.get("session_id"))  # multi-agent
    chain_id = args["chainId"]
    max_clusters = min(args.get("maxClusters", 5), 10)

    if chain_id not in session.chains:
        return {"content": [{"type": "text", "text": f"Error: Chain '{chain_id}' not found"}]}

    chain = session.chains[chain_id]
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
    session = _get_session(args.get("session_id"))  # multi-agent
    chain_id = args["chainId"]
    fmt = args.get("format", "markdown")

    if chain_id not in session.chains:
        return {"content": [{"type": "text", "text": f"Error: Chain '{chain_id}' not found"}]}

    chain = session.chains[chain_id]
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
        if i > 1:
            lines.append(f"**Depends on**: Step {i - 1}")
        lines.append("")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_thought_evaluate(args: dict) -> dict:
    """Evaluate thought quality."""
    session = _get_session(args.get("session_id"))  # multi-agent
    chain_id = args["chainId"]
    thought_number = args["thoughtNumber"]

    if chain_id not in session.chains:
        return {"content": [{"type": "text", "text": f"Error: Chain '{chain_id}' not found"}]}

    chain = session.chains[chain_id]
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
    session = _get_session(args.get("session_id"))  # multi-agent
    thought_text = args["thought"]
    top_n = min(args.get("topN", 3), 5)

    if len(session.chains) < 2:
        return {"content": [{"type": "text", "text": "Need at least 2 chains for cross-chain bridging."}]}

    # Build query vector
    query_tokens = _tokenize(thought_text)
    if not query_tokens:
        return {"content": [{"type": "text", "text": "No meaningful tokens in thought to bridge."}]}

    connections = []
    for cid, chain in session.chains.items():
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
    session = _get_session(args.get("session_id"))  # multi-agent
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
    session.assumptions.append(assumption)
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
    unverified = [a for a in session.assumptions if a["status"] == "unverified" and a["id"] != assumption["id"]]
    if unverified:
        lines.append(f"\n   ⚠️  You have {len(unverified)} other unverified assumption(s):")
        for a in unverified[-3:]:
            lines.append(f"      #{a['id']}: {a['statement'][:80]}...")
        if len(unverified) > 3:
            lines.append(f"      ... and {len(unverified)-3} more. Use list_assumptions() to see all.")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_list_assumptions(args: dict) -> dict:
    """List assumptions with optional filtering."""
    session = _get_session(args.get("session_id"))  # multi-agent
    status_filter = args.get("status", "unverified")
    category_filter = args.get("category")

    filtered = session.assumptions
    if status_filter != "all":
        filtered = [a for a in filtered if a["status"] == status_filter]
    if category_filter:
        filtered = [a for a in filtered if a["category"] == category_filter]

    if not filtered:
        return {"content": [{"type": "text", "text": f"No assumptions found (filter: status={status_filter}, category={category_filter or 'any'})."}]}

    total = len(session.assumptions)
    confirmed = sum(1 for a in session.assumptions if a["status"] == "confirmed")
    refuted = sum(1 for a in session.assumptions if a["status"] == "refuted")
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
    session = _get_session(args.get("session_id"))  # multi-agent
    aid = args["assumption_id"]
    outcome = args["outcome"]
    evidence = args.get("evidence", "")

    target = None
    for a in session.assumptions:
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
    confirmed = sum(1 for a in session.assumptions if a["status"] == "confirmed")
    refuted = sum(1 for a in session.assumptions if a["status"] == "refuted")
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


def _update_dependents(session: Session):
    """Recalculate reverse dependencies (who depends on whom)."""
    for path in session.model:
        session.model[path]["dependents"] = []
    for path, node in session.model.items():
        for dep in node.get("deps", []):
            if dep in session.model:
                session.model[dep]["dependents"].append(path)


def tool_model_add(args: dict) -> dict:
    """Add a file to the mental model."""
    session = _get_session(args.get("session_id"))  # multi-agent
    path = args["path"]
    # Normalize to forward slashes for cross-platform consistency
    path = path.replace("\\", "/")
    role = args.get("role", "other")
    deps = args.get("deps", [])
    notes = args.get("notes", "")

    existing = path in session.model

    session.model[path] = {
        "role": role,
        "deps": list(deps),
        "dependents": [],
        "notes": notes,
        "added_at": time.time(),
    }
    _update_dependents(session)

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
    for p, node in session.model.items():
        if path in node.get("deps", []) and p != path:
            connected.add(p)
    if connected:
        lines.append(f"   🔗 Connected: {len(connected)} file(s)")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_model_query(args: dict) -> dict:
    """Query the mental model."""
    session = _get_session(args.get("session_id"))  # multi-agent
    query = args["query"].strip()
    target = args.get("target", "")

    if not session.model:
        return {"content": [{"type": "text", "text": "Model is empty. Use model_add to populate it first."}]}

    lines = []

    # "deps of path"
    if query.startswith("deps of ") or query.startswith("deps "):
        path = target or query.replace("deps of ", "").replace("deps ", "").strip()
        if path in session.model:
            deps = session.model[path].get("deps", [])
            lines.append(f"📦 Dependencies of {path} ({session.model[path].get('role','?')}):")
            for d in deps:
                role_str = f" [{session.model[d]['role']}]" if d in session.model else " [unknown]"
                lines.append(f"   → {d}{role_str}")
            if not deps:
                lines.append("   (no dependencies)")
        else:
            lines.append(f"❌ '{path}' not in model. Add it with model_add first.")

    # "dependents of path" / "who depends on path"
    elif "dependent" in query or "who depends" in query:
        path = target or query.split("of ")[-1].strip()
        if path in session.model:
            deps_of = session.model[path].get("dependents", [])
            lines.append(f"📦 Files that depend on {path}:")
            for d in deps_of:
                lines.append(f"   ← {d} [{session.model[d].get('role','?')}]")
            if not deps_of:
                lines.append(f"   ✅ No files depend on {path} — safe to change!")
        else:
            lines.append(f"❌ '{path}' not in model.")

    # "role=X"
    elif query.startswith("role="):
        role = query.replace("role=", "").strip()
        matches = [p for p, n in session.model.items() if n.get("role") == role]
        lines.append(f"📦 Files with role '{role}' ({len(matches)}):")
        for m in sorted(matches):
            lines.append(f"   {m}" + (f" — {session.model[m].get('notes','')[:60]}" if session.model[m].get('notes') else ""))

    # "impact of path"
    elif "impact" in query:
        path = target or query.split("of ")[-1].strip()
        if path in session.model:
            deps_of = session.model[path].get("dependents", [])
            lines.append(f"💥 Impact of changing {path}:")
            if deps_of:
                lines.append(f"   {len(deps_of)} file(s) would be affected:")
                for d in deps_of:
                    lines.append(f"   ⚠️  {d} [{session.model[d].get('role','?')}]")
            else:
                lines.append(f"   ✅ No impact — safe to change!")
        else:
            lines.append(f"❌ '{path}' not in model.")

    # "all"
    elif query == "all":
        lines.append(f"📦 Full model ({len(session.model)} files):")
        for path in sorted(_model):
            n = session.model[path]
            lines.append(f"   {path} [{n.get('role','?')}] → {len(n.get('deps',[]))} deps, {len(n.get('dependents',[]))} users")

    else:
        lines.append(f"❓ Unknown query: '{query}'")
        lines.append("Try: 'deps of <path>', 'dependents of <path>', 'role=<name>', 'impact of <path>', 'all'")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_model_stats(args: dict) -> dict:
    """Model statistics."""
    session = _get_session(args.get("session_id"))  # multi-agent
    if not session.model:
        return {"content": [{"type": "text", "text": "Model is empty."}]}

    roles = Counter(n.get("role", "other") for n in session.model.values())
    total_deps = sum(len(n.get("deps", [])) for n in session.model.values())
    total_files = len(session.model)
    avg_deps = total_deps / total_files if total_files else 0

    # Most connected files
    connections = [(p, len(n.get("deps", [])) + len(n.get("dependents", []))) for p, n in session.model.items()]
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
        n = session.model[path]
        lines.append(f"   {path} [{n.get('role','?')}] — {conn} connections")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_model_map(args: dict) -> dict:
    """Visual tree map of the model."""
    session = _get_session(args.get("session_id"))  # multi-agent
    if not session.model:
        return {"content": [{"type": "text", "text": "Model is empty."}]}

    root = args.get("root_path", ".")
    max_depth = args.get("max_depth", 3)

    # Build tree from paths
    lines = [f"🗺️  Project Map:"]

    # Find entry points (files with no incoming deps from the model)
    has_dependents = set()
    for n in session.model.values():
        for d in n.get("dependents", []):
            has_dependents.add(d)

    # Entry points: files with dependents but no deps within model, OR files with deps but no dependents
    entries = sorted(session.model.keys())

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
            n = session.model[path]
            fname = os.path.basename(path)
            role_icon = {"authentication":"🔐","database":"🗄️","config":"⚙️","api":"🔌","model":"📊","test":"🧪","util":"🔧","entry_point":"🚀"}.get(n.get("role",""),"📄")
            deps_str = f" → {', '.join(n.get('deps',[])[:3])}" if n.get("deps") else ""
            lines.append(f"   {role_icon} {fname} [{n.get('role','?')}]{deps_str}")

    lines.append(f"\n📊 {len(session.model)} files mapped across {len(dirs)} directories")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_model_remove(args: dict) -> dict:
    """Remove a file from the mental model."""
    session = _get_session(args.get("session_id"))  # multi-agent
    path = args["path"]

    if path not in _model:
        return {"content": [{"type": "text", "text": f"'{path}' is not in the model."}]}

    # Find what depends on this file
    affected = session.model[path].get("dependents", [])
    role = session.model[path].get("role", "?")

    del session.model[path]
    _update_dependents(session)

    lines = [f"🗑️  Removed from model: {path} [{role}]"]
    if affected:
        lines.append(f"   ⚠️  {len(affected)} file(s) had this as dependency:")
        for a in affected:
            lines.append(f"      {a} — check if still valid")
    lines.append(f"   Model now has {len(session.model)} file(s)")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_model_scan(args: dict) -> dict:
    """Auto-scan a directory and build the mental model."""
    session = _get_session(args.get("session_id"))  # multi-agent
    scan_path = args.get("path", ".")
    patterns = args.get("file_patterns", ["*.py", "*.js", "*.ts", "*.rs", "*.go"])
    max_files = min(args.get("max_files", 100), 500)

    scan_dir = Path(scan_path)
    if not scan_dir.exists() or not scan_dir.is_dir():
        return {"content": [{"type": "text", "text": f"Error: Directory not found: {scan_path}"}]}

    # Discover files matching patterns
    discovered = []
    for pat in patterns:
        for f in scan_dir.rglob(pat):
            if len(discovered) >= max_files:
                break
            # Skip hidden dirs and common excludes
            parts = f.parts
            if any(p.startswith(".") and p != "." for p in parts):
                continue
            if any(p in ("node_modules", "__pycache__", ".git", "venv", "dist", "build", ".hermes") for p in parts):
                continue
            discovered.append(f)
        if len(discovered) >= max_files:
            break

    discovered = discovered[:max_files]

    # Guess role from filename and path
    def guess_role(filepath: Path) -> str:
        name = filepath.stem.lower()
        path_str = str(filepath).lower()
        if "test" in name or "spec" in name:
            return "test"
        if "auth" in name or "login" in name or "session" in name:
            return "authentication"
        if "db" in name or "database" in name or "model" in name or "schema" in name:
            return "database"
        if "api" in name or "route" in name or "endpoint" in name or "handler" in name:
            return "api"
        if "config" in name or "setting" in name or ".env" in name:
            return "config"
        if "main" in name or "index" in name or "app" in name or "server" in name:
            return "entry_point"
        if "util" in name or "helper" in name or "common" in name:
            return "util"
        if name.startswith("test_"):
            return "test"
        return "other"

    # Detect import dependencies for Python files
    def detect_deps(filepath: Path) -> list:
        deps = []
        if filepath.suffix != ".py":
            return deps
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        except:
            return deps
        # Simple from/import detection
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("from ") or line.startswith("import "):
                # Extract module names
                parts = line.replace("from ", "").replace("import ", "").split()
                if parts:
                    mod = parts[0]
                    # Convert dotted module to potential file path
                    mod_path = mod.replace(".", os.sep) + ".py"
                    # Check if this module exists in the scanned directory
                    for d in discovered:
                        if str(d).endswith(mod_path) or d.stem == mod.split(".")[-1]:
                            rel = str(d.relative_to(scan_dir)) if d.is_relative_to(scan_dir) else str(d)
                            deps.append(rel)
                            break
        return deps[:10]  # Cap deps

    # Build model
    added = 0
    updated = 0
    for f in discovered:
        try:
            rel = str(f.relative_to(scan_dir))
        except ValueError:
            rel = str(f)
        # Normalize to forward slashes for cross-platform query consistency
        rel = rel.replace("\\", "/")
        role = guess_role(f)
        deps = detect_deps(f)

        existing = rel in _model
        session.model[rel] = {
            "role": role,
            "deps": deps,
            "dependents": [],
            "notes": f"Auto-scanned from {scan_path}",
            "added_at": time.time(),
        }
        if existing:
            updated += 1
        else:
            added += 1

    _update_dependents(session)

    lines = [
        f"🔍 Scanned {scan_path}",
        f"   Files found:    {len(discovered)}",
        f"   Added to model: {added}",
        f"   Updated:        {updated}",
        f"   Total in model: {len(session.model)}",
        f"",
        f"   Use model_map() to visualize or model_query() to explore.",
    ]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


# ═══════════════════════════════════════════════════════════════════════
# Context Decay Detector — preserve critical info from context loss
# ═══════════════════════════════════════════════════════════════════════

_preserved: list[dict] = []


def tool_context_preserve(args: dict) -> dict:
    """Mark information as worth preserving."""
    content = args["content"]
    priority = args.get("priority", "high")
    category = args.get("category", "other")

    item = {
        "content": content,
        "priority": priority,
        "category": category,
        "timestamp": time.time(),
    }
    _preserved.append(item)

    priority_icon = {"critical": "🔴", "high": "🟡", "medium": "🟢"}.get(priority, "⚪")
    lines = [
        f"{priority_icon} Preserved [{priority}] [{category}]:",
        f"   \"{content[:200]}\"",
    ]

    # Warn if list is growing
    critical_count = sum(1 for p in _preserved if p["priority"] == "critical")
    total = len(_preserved)
    lines.append(f"   📊 Preservation list: {total} items ({critical_count} critical)")

    if total > 15:
        lines.append(f"   ⚠️  List is large ({total} items). Consider using thought_summarize to condense.")
    if total > 30:
        lines.append(f"   🚨 List is very large ({total} items). High risk of losing information.")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_context_check(args: dict) -> dict:
    """Check preserved items and decay risk."""
    max_items = args.get("max_items", 20)

    if not _preserved:
        return {"content": [{"type": "text", "text": "📋 No items preserved yet. Use context_preserve to mark critical information."}]}

    total = len(_preserved)
    by_priority = {"critical": 0, "high": 0, "medium": 0}
    by_category = {}
    for p in _preserved:
        by_priority[p["priority"]] = by_priority.get(p["priority"], 0) + 1
        cat = p["category"]
        by_category[cat] = by_category.get(cat, 0) + 1

    lines = [f"📋 Context Preservation Check — {total} items"]
    lines.append(f"   🔴 {by_priority.get('critical',0)} critical | 🟡 {by_priority.get('high',0)} high | 🟢 {by_priority.get('medium',0)} medium")
    lines.append("")

    # Risk assessment
    if total > 20:
        lines.append(f"   🚨 HIGH DECAY RISK: {total} items preserved.")
        lines.append(f"   💡 Actions: (1) use thought_summarize to condense,")
        lines.append(f"        (2) move non-critical items to memory,")
        lines.append(f"        (3) prioritize critical items only.")
    elif total > 10:
        lines.append(f"   ⚠️  MEDIUM DECAY RISK: {total} items. Monitor closely.")
    else:
        lines.append(f"   ✅ LOW DECAY RISK: {total} items. Context should be stable.")

    # Show by category
    lines.append(f"\n   By category:")
    for cat, count in sorted(by_category.items(), key=lambda x: -x[1]):
        lines.append(f"   {cat:<15} {'█' * min(count, 20)} {count}")

    # Show most recent critical/high
    lines.append(f"\n   Recent critical/high items:")
    shown = 0
    for p in reversed(_preserved):
        if p["priority"] in ("critical", "high") and shown < max_items:
            icon = {"critical": "🔴", "high": "🟡"}.get(p["priority"], "⚪")
            lines.append(f"   {icon} [{p['category']}] {p['content'][:120]}...")
            shown += 1
        if shown >= 10:
            break

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


# ═══════════════════════════════════════════════════════════════════════
# Work Tracker — persistent work log across sessions
# ═══════════════════════════════════════════════════════════════════════

_works: list[dict] = []
_next_work_id = 1
WORK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".work_log.json")

def _load_works():
    """Load persisted work log from disk."""
    # global _works, _next_work_id  # legacy, use session.works
    try:
        if os.path.exists(WORK_FILE):
            with open(WORK_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                session.works = data.get("works", [])
                _next_work_id = data.get("next_id", 1)
    except Exception:
        pass

def _save_works():
    """Persist work log to disk."""
    try:
        os.makedirs(os.path.dirname(WORK_FILE), exist_ok=True)
        with open(WORK_FILE, 'w', encoding='utf-8') as f:
            json.dump({"works": session.works, "next_id": _next_work_id}, f, indent=2)
    except Exception:
        pass

_load_works()


def tool_work_start(args: dict) -> dict:
    """Start tracking a work item."""
    # global _next_work_id  # legacy

    item = args["item"]
    category = args.get("category", "other")

    work = {
        "id": _next_work_id,
        "item": item,
        "category": category,
        "status": "in_progress",
        "started_at": time.time(),
        "blocked_at": None,
        "blocked_reason": "",
        "done_at": None,
        "result": "",
    }
    session.works.append(work)
    _next_work_id += 1
    _save_works()

    in_progress = sum(1 for w in session.works if w["status"] == "in_progress")
    lines = [
        f"🔧 Work #{work['id']} started: {item}",
        f"   Category: {category}",
        f"   You have {in_progress} active work item(s)",
    ]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_work_block(args: dict) -> dict:
    """Mark a work item as blocked."""
    wid = args["work_id"]
    reason = args["reason"]

    for w in session.works:
        if w["id"] == wid:
            w["status"] = "blocked"
            w["blocked_at"] = time.time()
            w["blocked_reason"] = reason
            _save_works()
            return {"content": [{"type": "text", "text": f"🚫 Work #{wid} blocked: {reason}"}]}

    return {"content": [{"type": "text", "text": f"Error: Work #{wid} not found."}]}


def tool_work_done(args: dict) -> dict:
    """Mark a work item as done."""
    wid = args["work_id"]
    result = args.get("result", "")

    for w in session.works:
        if w["id"] == wid:
            w["status"] = "done"
            w["done_at"] = time.time()
            w["result"] = result
            _save_works()
            lines = [f"✅ Work #{wid} completed: {w['item']}"]
            if result:
                lines.append(f"   Result: {result}")
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    return {"content": [{"type": "text", "text": f"Error: Work #{wid} not found."}]}


def tool_work_log(args: dict) -> dict:
    """Show work log."""
    status_filter = args.get("status", "all")
    limit = args.get("limit", 20)

    filtered = session.works
    if status_filter != "all":
        filtered = [w for w in filtered if w["status"] == status_filter]
    filtered = filtered[-limit:]

    if not filtered:
        return {"content": [{"type": "text", "text": "No work items found. Use work_start to begin tracking."}]}

    in_progress = sum(1 for w in session.works if w["status"] == "in_progress")
    blocked = sum(1 for w in session.works if w["status"] == "blocked")
    done = sum(1 for w in session.works if w["status"] == "done")

    lines = [f"📋 Work Log ({len(filtered)} shown, {len(session.works)} total)"]
    lines.append(f"   🔧 {in_progress} in progress | 🚫 {blocked} blocked | ✅ {done} done")
    lines.append("")

    icons = {"in_progress": "🔧", "blocked": "🚫", "done": "✅"}
    for w in filtered:
        icon = icons.get(w["status"], "?")
        lines.append(f"   {icon} #{w['id']} [{w['category']}] {w['item'][:100]}")
        if w["status"] == "blocked" and w.get("blocked_reason"):
            lines.append(f"      Blocked: {w['blocked_reason'][:80]}")
        if w["status"] == "done" and w.get("result"):
            lines.append(f"      Result: {w['result'][:80]}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


# ═══════════════════════════════════════════════════════════════════════
# Context Estimator — heuristic context usage assessment
# ═══════════════════════════════════════════════════════════════════════

_session_start = time.time()
_tool_calls = 0
_estimated_chars = 0


def tool_context_estimate(args: dict) -> dict:
    """Estimate context usage."""
    session = _get_session(args.get("session_id"))
    uptime = time.time() - _session_start
    tool_estimate = _tool_calls * 500
    content_estimate = _estimated_chars // 4
    total_est = tool_estimate + content_estimate
    context_limit = 80_000
    pct = min(100, (total_est * 100) // context_limit)
    if pct > 70:
        risk = "HIGH"; suggestion = "Consider externalizing key thoughts to sequential_thinking and summarizing with thought_summarize."
    elif pct > 40:
        risk = "MEDIUM"; suggestion = "Monitor. Use context_preserve for critical findings."
    else:
        risk = "LOW"; suggestion = "Context is healthy. No action needed."
    lines = [
        f"📊 Context Estimate: ~{pct}% used (risk: {risk})",
        f"   Session: {uptime:.0f}s | Tool calls: {_tool_calls} | Est. tokens: ~{total_est:,}",
        f"   Model limit: ~{context_limit:,} tokens",
        f"", f"   💡 {suggestion}",
    ]
    if risk == "HIGH":
        lines += ["   ⚡ Actions:", "      • Use sequential_thinking to offload reasoning",
                   "      • Use context_preserve for must-keep information",
                   "      • Use thought_summarize to condense chains",
                   "      • Avoid large read_files — use search_with_context instead"]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


# ═══════════════════════════════════════════════════════════════════════
# Session Management Tools
# ═══════════════════════════════════════════════════════════════════════

def tool_session_init(args: dict) -> dict:
    """Create or retrieve a multi-agent session."""
    global _next_session_num
    label = args.get("label", "")
    sid = args.get("session_id")

    if sid and sid in _sessions:
        session = _sessions[sid]
        action = "resumed"
    else:
        if not sid:
            sid = f"session_{_next_session_num}"
            _next_session_num += 1
        _sessions[sid] = Session(label=label or sid)
        session = _sessions[sid]
        action = "created"

    return {"content": [{"type": "text", "text": (
        f"🟢 Session {action}: {sid}\n"
        f"   Label: {session.label}\n"
        f"   Chains: {len(session.chains)}\n"
        f"   Assumptions: {len(session.assumptions)}\n"
        f"   Model files: {len(session.model)}\n"
        f"   Works: {len(session.works)}\n"
        f"   Use session_id='{sid}' in subsequent tool calls to keep state isolated."
    )}]}

def tool_session_list(args: dict) -> dict:
    """List all active sessions."""
    if not _sessions:
        return {"content": [{"type": "text", "text": "No active sessions. Use session_init to create one."}]}

    lines = ["📋 Active Sessions:"]
    for sid, s in sorted(_sessions.items()):
        age = time.time() - s.updated_at
        lines.append(
            f"   {sid}: {s.label or '(no label)'} | "
            f"{len(s.chains)} chains, {len(s.assumptions)} asmp, "
            f"{len(s.model)} model, {s.tool_calls} calls | "
            f"idle {age:.0f}s"
        )
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}
    uptime = time.time() - _session_start
    tool_estimate = _tool_calls * 500  # Rough: 500 tokens per tool call
    content_estimate = _estimated_chars // 4  # Rough: 4 chars per token

    total_est = tool_estimate + content_estimate
    # Most models have ~128K context. Hermes typically uses ~60-80K with system prompt.
    context_limit = 80_000
    pct = min(100, (total_est * 100) // context_limit)

    # Risk level
    if pct > 70:
        risk = "HIGH"
        suggestion = "Consider externalizing key thoughts to sequential_thinking and summarizing with thought_summarize."
    elif pct > 40:
        risk = "MEDIUM"
        suggestion = "Monitor. Use context_preserve for critical findings."
    else:
        risk = "LOW"
        suggestion = "Context is healthy. No action needed."

    lines = [
        f"📊 Context Estimate: ~{pct}% used (risk: {risk})",
        f"   Session: {uptime:.0f}s | Tool calls: {_tool_calls} | Est. tokens: ~{total_est:,}",
        f"   Model limit: ~{context_limit:,} tokens",
        f"",
        f"   💡 {suggestion}",
    ]

    # Additional suggestions based on risk
    if risk == "HIGH":
        lines.append(f"   ⚡ Actions:")
        lines.append(f"      • Use sequential_thinking to offload reasoning")
        lines.append(f"      • Use context_preserve for must-keep information")
        lines.append(f"      • Use thought_summarize to condense chains")
        lines.append(f"      • Avoid large read_files — use search_with_context instead")

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
    "model_scan": tool_model_scan,
    "context_preserve": tool_context_preserve,
    "context_check": tool_context_check,
    "work_start": tool_work_start,
    "work_block": tool_work_block,
    "work_done": tool_work_done,
    "work_log": tool_work_log,
    "context_estimate": tool_context_estimate,
    "session_init": tool_session_init,
    "session_list": tool_session_list,
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
        global _tool_calls, _estimated_chars
        _tool_calls += 1
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
